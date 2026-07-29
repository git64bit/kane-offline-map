#include "trivialhttp.h"

static int ensure_sector_directory(const TrivialHttpOptions *options, char *out, size_t size) {
  char parent[PATH_MAX];
  if (th_join_root(options, TH_STORAGE_PARENT, parent, sizeof(parent)) ||
      th_ensure_safe_directory(parent)) return -1;
  if (th_strlcpy(out, parent, size) || th_append_separator(out, size) ||
      th_strlcat(out, TH_STORAGE_CHILD, size) || th_ensure_safe_directory(out)) return -1;
  return 0;
}

static int valid_sector_filename(const char *name) {
  if (strlen(name) != 12 || name[0] != 'N' || name[3] != '-' || name[4] != 'E' ||
      strcmp(name + 7, ".json")) return 0;
  if (!isdigit((unsigned char)name[1]) || !isdigit((unsigned char)name[2]) ||
      !isdigit((unsigned char)name[5]) || !isdigit((unsigned char)name[6])) return 0;
  int north = (name[1] - '0') * 10 + name[2] - '0';
  int east = (name[5] - '0') * 10 + name[6] - '0';
  return north >= 11 && north <= 14 && east >= 6 && east <= 9;
}

int th_sector_route(const char *url, char *file_name, size_t size) {
  char decoded[PATH_MAX];
  if (th_decode_url_path(url, decoded, sizeof(decoded))) return -1;
  const char *roots[] = { TH_API_ROOT, TH_LEGACY_API_ROOT };
  for (size_t index = 0; index < sizeof(roots) / sizeof(roots[0]); index++) {
    const char *root = roots[index];
    if (!strcmp(decoded, root) || (!strncmp(decoded, root, strlen(root)) && !strcmp(decoded + strlen(root), "/"))) {
      return 1;
    }
    size_t prefix = strlen(root);
    if (strncmp(decoded, root, prefix) || decoded[prefix] != '/') continue;
    const char *name = decoded + prefix + 1;
    if (!valid_sector_filename(name) || th_strlcpy(file_name, name, size)) return -1;
    return 2;
  }
  return 0;
}

static int looks_like_sector_json(const HttpRequest *request, const char *file_name) {
  if (!request->body || !request->body_len) return 0;
  const char *start = request->body;
  while (*start && isspace((unsigned char)*start)) start++;
  const char *end = request->body + request->body_len;
  while (end > start && isspace((unsigned char)end[-1])) end--;
  char sector[8];
  memcpy(sector, file_name, 7);
  sector[7] = '\0';
  return end > start && *start == '{' && end[-1] == '}' &&
    (strstr(start, "\"county-field-map-sector-state\"") ||
     strstr(start, "\"kane-map-sector-state\"")) && strstr(start, sector);
}

static int atomic_write(const char *target, const void *body, size_t length) {
  char temp[PATH_MAX];
  if (th_strlcpy(temp, target, sizeof(temp)) || th_strlcat(temp, ".tmp", sizeof(temp))) return -1;
  remove(temp);
  FILE *file = fopen(temp, "wb");
  if (!file) return -1;
  int ok = fwrite(body, 1, length, file) == length && !fflush(file) && !th_sync_file(file);
  if (fclose(file)) ok = 0;
  if (!ok || th_replace_file(temp, target)) {
    remove(temp);
    return -1;
  }
  return 0;
}

void th_serve_sector_api(th_socket_t client, const TrivialHttpOptions *options,
  const HttpRequest *request, int route, const char *file_name) {
  int is_head = !strcmp(request->method, "HEAD");
  char directory[PATH_MAX];
  if (ensure_sector_directory(options, directory, sizeof(directory))) {
    th_send_json(client, 500, "Internal Server Error",
      "{\"ok\":false,\"error\":\"Sector storage directory is unavailable.\"}\n", 0);
    return;
  }
  if (route == 1) {
    if (strcmp(request->method, "GET") && !is_head) {
      th_send_text(client, 405, "Method Not Allowed", "Method not allowed.\n", "Allow: GET, HEAD\r\n");
      return;
    }
    th_send_json(client, 200, "OK",
      "{\"ok\":true,\"storage\":\"project-data/sectors\",\"sectorCount\":16}\n", is_head);
    return;
  }
  char target[PATH_MAX];
  if (th_strlcpy(target, directory, sizeof(target)) || th_append_separator(target, sizeof(target)) ||
      th_strlcat(target, file_name, sizeof(target))) {
    th_send_json(client, 500, "Internal Server Error",
      "{\"ok\":false,\"error\":\"Sector path is too long.\"}\n", 0);
    return;
  }
  if (!strcmp(request->method, "GET") || is_head) {
    if (!th_file_is_regular(target)) {
      th_send_json(client, 404, "Not Found",
        "{\"ok\":false,\"error\":\"Sector file not found.\"}\n", is_head);
      return;
    }
    th_serve_disk_file(client, target, is_head, "application/json; charset=utf-8");
  } else if (!strcmp(request->method, "PUT")) {
    if (!looks_like_sector_json(request, file_name)) {
      th_send_json(client, 400, "Bad Request",
        "{\"ok\":false,\"error\":\"Invalid County Field Map sector JSON.\"}\n", 0);
      return;
    }
    if (atomic_write(target, request->body, request->body_len)) {
      th_send_json(client, 500, "Internal Server Error",
        "{\"ok\":false,\"error\":\"Sector file could not be written.\"}\n", 0);
      return;
    }
    char response[128];
    snprintf(response, sizeof(response), "{\"ok\":true,\"sector\":\"%.7s\"}\n", file_name);
    th_send_json(client, 200, "OK", response, 0);
  } else {
    th_send_text(client, 405, "Method Not Allowed", "Method not allowed.\n",
      "Allow: GET, HEAD, PUT\r\n");
  }
}
