#include "trivialhttp.h"

void th_send_response(th_socket_t client, int status, const char *reason,
  const char *type, const void *body, size_t body_len, const char *extra_headers, int is_head) {
  char header[TH_SMALL_BUF];
  int length = snprintf(header, sizeof(header),
    "HTTP/1.1 %d %s\r\nServer: TrivialHTTP/%s\r\nContent-Type: %s\r\n"
    "Content-Length: %zu\r\nCache-Control: no-store\r\nConnection: close\r\n%s\r\n",
    status, reason, TH_VERSION, type, body_len, extra_headers ? extra_headers : "");
  if (length > 0) th_send_all(client, header, (size_t)length);
  if (!is_head && body && body_len) th_send_all(client, body, body_len);
}

void th_send_text(th_socket_t client, int status, const char *reason,
  const char *message, const char *extra_headers) {
  th_send_response(client, status, reason, "text/plain; charset=utf-8",
    message, strlen(message), extra_headers, 0);
}

void th_send_json(th_socket_t client, int status, const char *reason, const char *json, int is_head) {
  th_send_response(client, status, reason, "application/json; charset=utf-8",
    json, strlen(json), NULL, is_head);
}

static int hex_value(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

int th_decode_url_path(const char *url, char *out, size_t size) {
  size_t used = 0;
  for (const char *p = url; *p && *p != '?' && *p != '#';) {
    unsigned char c;
    if (*p == '%') {
      int high = hex_value(p[1]), low = hex_value(p[2]);
      if (high < 0 || low < 0) return -1;
      c = (unsigned char)((high << 4) | low);
      p += 3;
    } else {
      c = (unsigned char)*p++;
    }
    if (!c || c < 32 || c == 127) return -1;
    if (c == '\\') c = '/';
    if (used + 1 >= size) return -1;
    out[used++] = (char)c;
  }
  out[used] = '\0';
  return 0;
}

static int unsafe_path_segments(const char *path) {
  char segment[PATH_MAX];
  size_t used = 0;
  for (const char *p = path;; p++) {
    char c = *p;
    if (c == ':' || c == '/' || !c) {
      segment[used] = '\0';
      if (!strcmp(segment, "..")) return 1;
      used = 0;
      if (!c) break;
    } else if (used + 1 >= sizeof(segment)) {
      return 1;
    } else {
      segment[used++] = c;
    }
  }
  return 0;
}

static const char *mime_type_for_path(const char *path) {
  const char *dot = strrchr(path, '.');
  if (!dot) return "application/octet-stream";
  if (!strcmp(dot, ".html") || !strcmp(dot, ".htm")) return "text/html; charset=utf-8";
  if (!strcmp(dot, ".js") || !strcmp(dot, ".mjs")) return "application/javascript; charset=utf-8";
  if (!strcmp(dot, ".css")) return "text/css; charset=utf-8";
  if (!strcmp(dot, ".json") || !strcmp(dot, ".map")) return "application/json; charset=utf-8";
  if (!strcmp(dot, ".txt")) return "text/plain; charset=utf-8";
  if (!strcmp(dot, ".csv")) return "text/csv; charset=utf-8";
  if (!strcmp(dot, ".svg")) return "image/svg+xml";
  if (!strcmp(dot, ".png")) return "image/png";
  if (!strcmp(dot, ".jpg") || !strcmp(dot, ".jpeg")) return "image/jpeg";
  if (!strcmp(dot, ".webp")) return "image/webp";
  if (!strcmp(dot, ".ico")) return "image/x-icon";
  if (!strcmp(dot, ".wasm")) return "application/wasm";
  return "application/octet-stream";
}

static int build_local_path(const TrivialHttpOptions *options, const char *url,
  char *local_path, size_t size) {
  char decoded[PATH_MAX], relative[PATH_MAX];
  if (th_decode_url_path(url, decoded, sizeof(decoded))) return 400;
  const char *trimmed = decoded;
  while (*trimmed == '/') trimmed++;
  if (unsafe_path_segments(trimmed)) return 403;
  if (th_strlcpy(relative, trimmed, sizeof(relative))) return 414;
  if (!relative[0] || relative[strlen(relative) - 1] == '/') {
    if (th_strlcat(relative, "index.html", sizeof(relative))) return 414;
  }
  return th_join_root(options, relative, local_path, size) ? 414 : 0;
}

static int parse_content_length(const char *headers, size_t length, size_t *value, int *present) {
  *value = 0;
  *present = 0;
  const char *line = strstr(headers, "\r\n");
  if (!line) return -1;
  line += 2;
  const char *end = headers + length;
  while (line < end && line[0] != '\r') {
    const char *next = strstr(line, "\r\n");
    if (!next || next > end) return -1;
    const char key[] = "Content-Length:";
    if ((size_t)(next - line) >= sizeof(key) - 1 &&
        !th_ascii_ncasecmp(line, key, sizeof(key) - 1)) {
      const char *cursor = line + sizeof(key) - 1;
      while (cursor < next && (*cursor == ' ' || *cursor == '\t')) cursor++;
      if (cursor == next) return -1;
      size_t parsed = 0;
      for (; cursor < next; cursor++) {
        if (!isdigit((unsigned char)*cursor) || parsed > TH_BODY_MAX) return -2;
        parsed = parsed * 10u + (size_t)(*cursor - '0');
      }
      *value = parsed;
      *present = 1;
    }
    line = next + 2;
  }
  return 0;
}

int th_read_request(th_socket_t client, HttpRequest *request) {
  char headers[TH_HEADER_MAX + 1];
  size_t used = 0;
  char *boundary = NULL;
  memset(request, 0, sizeof(*request));
  while (!boundary) {
    if (used == TH_HEADER_MAX) return 431;
    int received = recv(client, headers + used, (int)(TH_HEADER_MAX - used), 0);
    if (received <= 0) return 400;
    used += (size_t)received;
    headers[used] = '\0';
    boundary = strstr(headers, "\r\n\r\n");
  }
  size_t header_len = (size_t)(boundary - headers) + 4;
  if (sscanf(headers, "%15s %4095s %31s", request->method, request->url, request->version) != 3 ||
      strncmp(request->version, "HTTP/", 5)) return 400;
  size_t content_length = 0;
  int content_present = 0;
  int parsed = parse_content_length(headers, header_len, &content_length, &content_present);
  if (parsed == -2 || content_length > TH_BODY_MAX) return 413;
  if (parsed) return 400;
  if (!strcmp(request->method, "PUT") && !content_present) return 411;
  if (!content_length) return 0;
  request->body = (char *)malloc(content_length + 1);
  if (!request->body) return 500;
  size_t available = used - header_len;
  size_t copied = available > content_length ? content_length : available;
  memcpy(request->body, headers + header_len, copied);
  while (copied < content_length) {
    int received = recv(client, request->body + copied, (int)(content_length - copied), 0);
    if (received <= 0) return 400;
    copied += (size_t)received;
  }
  request->body[content_length] = '\0';
  request->body_len = content_length;
  return 0;
}

void th_serve_disk_file(th_socket_t client, const char *path, int is_head, const char *content_type) {
  FILE *file = fopen(path, "rb");
  if (!file || fseek(file, 0, SEEK_END)) {
    if (file) fclose(file);
    th_send_text(client, 500, "Internal Server Error", "Could not read file.\n", NULL);
    return;
  }
  long size = ftell(file);
  if (size < 0) {
    fclose(file);
    th_send_text(client, 500, "Internal Server Error", "Could not read file.\n", NULL);
    return;
  }
  rewind(file);
  char header[TH_SMALL_BUF];
  int length = snprintf(header, sizeof(header),
    "HTTP/1.1 200 OK\r\nServer: TrivialHTTP/%s\r\nContent-Type: %s\r\n"
    "Content-Length: %ld\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
    TH_VERSION, content_type, size);
  if (length > 0) th_send_all(client, header, (size_t)length);
  if (!is_head) {
    char buffer[16384];
    size_t count;
    while ((count = fread(buffer, 1, sizeof(buffer), file)) > 0) {
      if (th_send_all(client, buffer, count)) break;
    }
  }
  fclose(file);
}

void th_serve_static(th_socket_t client, const TrivialHttpOptions *options, const HttpRequest *request) {
  int is_head = !strcmp(request->method, "HEAD");
  if (strcmp(request->method, "GET") && !is_head) {
    th_send_text(client, 405, "Method Not Allowed", "Method not allowed.\n", "Allow: GET, HEAD\r\n");
    return;
  }
  char candidate[PATH_MAX], real[PATH_MAX];
  int result = build_local_path(options, request->url, candidate, sizeof(candidate));
  if (result == 400) th_send_text(client, 400, "Bad Request", "Bad request.\n", NULL);
  else if (result == 403) th_send_text(client, 403, "Forbidden", "Forbidden.\n", NULL);
  else if (result) th_send_text(client, 414, "URI Too Long", "URI too long.\n", NULL);
  else if (!th_file_is_regular(candidate)) th_send_text(client, 404, "Not Found", "Not found.\n", NULL);
  else if (th_canonical_path(candidate, real, sizeof(real)) || !th_path_under_root(options->root_real, real))
    th_send_text(client, 403, "Forbidden", "Forbidden.\n", NULL);
  else th_serve_disk_file(client, real, is_head, mime_type_for_path(real));
}

void th_handle_client(th_socket_t client, const TrivialHttpOptions *options) {
  HttpRequest request;
  int status = th_read_request(client, &request);
  if (status) {
    const char *reason = status == 411 ? "Length Required" : status == 413 ? "Payload Too Large" :
      status == 431 ? "Request Header Fields Too Large" :
      status == 500 ? "Internal Server Error" : "Bad Request";
    th_send_text(client, status, reason, "Request could not be processed.\n", NULL);
    free(request.body);
    return;
  }
  char file_name[32] = "";
  int route = th_sector_route(request.url, file_name, sizeof(file_name));
  if (route < 0) th_send_json(client, 400, "Bad Request",
    "{\"ok\":false,\"error\":\"Invalid sector endpoint.\"}\n", 0);
  else if (route) th_serve_sector_api(client, options, &request, route, file_name);
  else th_serve_static(client, options, &request);
  free(request.body);
}
