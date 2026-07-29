#include "trivialhttp.h"

int th_strlcpy(char *dst, const char *src, size_t size) {
  size_t len = strlen(src);
  if (!size) return -1;
  if (len >= size) {
    memcpy(dst, src, size - 1);
    dst[size - 1] = '\0';
    return -1;
  }
  memcpy(dst, src, len + 1);
  return 0;
}

int th_strlcat(char *dst, const char *src, size_t size) {
  size_t used = strlen(dst);
  return used < size ? th_strlcpy(dst + used, src, size - used) : -1;
}

int th_send_all(th_socket_t client, const void *data, size_t length) {
  const char *cursor = (const char *)data;
  while (length) {
    int sent = send(client, cursor, (int)(length > 65536 ? 65536 : length), 0);
    if (sent <= 0) return -1;
    cursor += sent;
    length -= (size_t)sent;
  }
  return 0;
}

int th_ascii_ncasecmp(const char *a, const char *b, size_t length) {
  for (size_t i = 0; i < length; i++) {
    int ca = tolower((unsigned char)a[i]);
    int cb = tolower((unsigned char)b[i]);
    if (ca != cb || !a[i] || !b[i]) return ca - cb;
  }
  return 0;
}

#ifdef _WIN32
static void normalize_separators(char *path) {
  for (; *path; path++) if (*path == '/') *path = '\\';
}

int th_canonical_path(const char *input, char *out, size_t size) {
  DWORD length = GetFullPathNameA(input, (DWORD)size, out, NULL);
  if (!length || length >= size) return -1;
  normalize_separators(out);
  size_t used = strlen(out);
  while (used > 3 && (out[used - 1] == '\\' || out[used - 1] == '/')) out[--used] = '\0';
  return 0;
}

int th_file_is_regular(const char *path) {
  DWORD attrs = GetFileAttributesA(path);
  return attrs != INVALID_FILE_ATTRIBUTES && !(attrs & FILE_ATTRIBUTE_DIRECTORY) &&
    !(attrs & FILE_ATTRIBUTE_REPARSE_POINT);
}

int th_ensure_safe_directory(const char *path) {
  DWORD attrs = GetFileAttributesA(path);
  if (attrs == INVALID_FILE_ATTRIBUTES) {
    if (!CreateDirectoryA(path, NULL) && GetLastError() != ERROR_ALREADY_EXISTS) return -1;
    attrs = GetFileAttributesA(path);
  }
  return attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_DIRECTORY) &&
    !(attrs & FILE_ATTRIBUTE_REPARSE_POINT) ? 0 : -1;
}

int th_path_under_root(const char *root, const char *candidate) {
  size_t length = strlen(root);
  return !_strnicmp(root, candidate, length) &&
    (!candidate[length] || candidate[length] == '\\' || candidate[length] == '/');
}

int th_sync_file(FILE *file) { return _commit(_fileno(file)); }
int th_replace_file(const char *temp, const char *target) {
  return MoveFileExA(temp, target, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) ? 0 : -1;
}
#else
int th_canonical_path(const char *input, char *out, size_t size) {
  if (!realpath(input, out) || strlen(out) >= size) return -1;
  size_t used = strlen(out);
  while (used > 1 && out[used - 1] == '/') out[--used] = '\0';
  return 0;
}

int th_file_is_regular(const char *path) {
  struct stat st;
  return !lstat(path, &st) && !S_ISLNK(st.st_mode) && S_ISREG(st.st_mode);
}

int th_ensure_safe_directory(const char *path) {
  struct stat st;
  if (!lstat(path, &st)) return !S_ISLNK(st.st_mode) && S_ISDIR(st.st_mode) ? 0 : -1;
  return errno == ENOENT && !mkdir(path, 0755) ? 0 : -1;
}

int th_path_under_root(const char *root, const char *candidate) {
  size_t length = strlen(root);
  return !strncmp(root, candidate, length) && (!candidate[length] || candidate[length] == '/');
}

int th_sync_file(FILE *file) { return fsync(fileno(file)); }
int th_replace_file(const char *temp, const char *target) { return rename(temp, target); }
#endif

int th_append_separator(char *path, size_t size) {
  size_t used = strlen(path);
  if (used && path[used - 1] != '/' && path[used - 1] != '\\') {
    char separator[2] = { TH_PATH_SEP, '\0' };
    return th_strlcat(path, separator, size);
  }
  return 0;
}

int th_join_root(const TrivialHttpOptions *options, const char *relative, char *out, size_t size) {
  char local[PATH_MAX];
  if (th_strlcpy(local, relative, sizeof(local))) return -1;
  for (char *p = local; *p; p++) if (*p == '/') *p = TH_PATH_SEP;
  return th_strlcpy(out, options->root_real, size) || th_append_separator(out, size) ||
    th_strlcat(out, local, size) ? -1 : 0;
}

int th_initialize_sockets(void) {
#ifdef _WIN32
  WSADATA wsa;
  return WSAStartup(MAKEWORD(2, 2), &wsa) ? -1 : 0;
#else
  signal(SIGPIPE, SIG_IGN);
  return 0;
#endif
}

void th_shutdown_sockets(void) {
#ifdef _WIN32
  WSACleanup();
#endif
}

th_socket_t th_create_listener(unsigned short requested, unsigned short *actual) {
  th_socket_t listener = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (listener == TH_INVALID_SOCKET) return TH_INVALID_SOCKET;
  int yes = 1;
#ifdef _WIN32
  setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, (const char *)&yes, sizeof(yes));
#else
  setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
#endif
  struct sockaddr_in address;
  memset(&address, 0, sizeof(address));
  address.sin_family = AF_INET;
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  address.sin_port = htons(requested);
  if (bind(listener, (struct sockaddr *)&address, sizeof(address)) || listen(listener, 16)) {
    TH_CLOSE(listener);
    return TH_INVALID_SOCKET;
  }
  TH_SOCKLEN length = sizeof(address);
  if (getsockname(listener, (struct sockaddr *)&address, &length)) {
    TH_CLOSE(listener);
    return TH_INVALID_SOCKET;
  }
  *actual = ntohs(address.sin_port);
  return listener;
}

void th_open_browser(const char *url) {
#ifdef _WIN32
  ShellExecuteA(NULL, "open", url, NULL, NULL, SW_SHOWNORMAL);
#else
  pid_t pid = fork();
  if (!pid) {
#ifdef __APPLE__
    execlp("open", "open", url, (char *)NULL);
#else
    execlp("xdg-open", "xdg-open", url, (char *)NULL);
#endif
    _exit(127);
  }
#endif
}
