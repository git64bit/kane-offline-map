#ifndef TRIVIALHTTP_H
#define TRIVIALHTTP_H

#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#define _XOPEN_SOURCE 700
#endif

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#ifndef _CRT_SECURE_NO_WARNINGS
#define _CRT_SECURE_NO_WARNINGS
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <direct.h>
#include <io.h>
#include <limits.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>
#if defined(_MSC_VER)
#pragma comment(lib, "Ws2_32.lib")
#pragma comment(lib, "Shell32.lib")
#endif
typedef SOCKET th_socket_t;
#define TH_CLOSE closesocket
#define TH_INVALID_SOCKET INVALID_SOCKET
#define TH_SOCKLEN int
#define TH_PATH_SEP '\\'
#ifndef PATH_MAX
#define PATH_MAX MAX_PATH
#endif
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <limits.h>
#include <netinet/in.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
typedef int th_socket_t;
#define TH_CLOSE close
#define TH_INVALID_SOCKET (-1)
#define TH_SOCKLEN socklen_t
#define TH_PATH_SEP '/'
#endif

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

#define TH_VERSION "0.3.0"
#define TH_HEADER_MAX 16384
#define TH_BODY_MAX (2u * 1024u * 1024u)
#define TH_SMALL_BUF 1024
#define TH_URL_BUF 2048
#define TH_API_ROOT "/__county_field_map/sector-state"
#define TH_LEGACY_API_ROOT "/__kane_map/sector-state"
#define TH_STORAGE_PARENT "project-data"
#define TH_STORAGE_CHILD "sectors"

typedef struct TrivialHttpOptions {
  char root[PATH_MAX];
  char root_real[PATH_MAX];
  char open_target[TH_SMALL_BUF];
  unsigned short port;
  int no_open;
  int once;
} TrivialHttpOptions;

typedef struct HttpRequest {
  char method[16];
  char url[PATH_MAX];
  char version[32];
  char *body;
  size_t body_len;
} HttpRequest;

int th_strlcpy(char *dst, const char *src, size_t size);
int th_strlcat(char *dst, const char *src, size_t size);
int th_send_all(th_socket_t client, const void *data, size_t length);
int th_ascii_ncasecmp(const char *a, const char *b, size_t length);
int th_canonical_path(const char *input, char *out, size_t size);
int th_file_is_regular(const char *path);
int th_ensure_safe_directory(const char *path);
int th_path_under_root(const char *root, const char *candidate);
int th_sync_file(FILE *file);
int th_replace_file(const char *temp, const char *target);
int th_append_separator(char *path, size_t size);
int th_join_root(const TrivialHttpOptions *options, const char *relative, char *out, size_t size);
int th_initialize_sockets(void);
void th_shutdown_sockets(void);
th_socket_t th_create_listener(unsigned short requested, unsigned short *actual);
void th_open_browser(const char *url);

void th_send_response(th_socket_t client, int status, const char *reason,
  const char *type, const void *body, size_t body_len, const char *extra_headers, int is_head);
void th_send_text(th_socket_t client, int status, const char *reason,
  const char *message, const char *extra_headers);
void th_send_json(th_socket_t client, int status, const char *reason, const char *json, int is_head);
int th_decode_url_path(const char *url, char *out, size_t size);
void th_serve_disk_file(th_socket_t client, const char *path, int is_head, const char *content_type);
void th_serve_static(th_socket_t client, const TrivialHttpOptions *options, const HttpRequest *request);
int th_read_request(th_socket_t client, HttpRequest *request);
void th_handle_client(th_socket_t client, const TrivialHttpOptions *options);

int th_sector_route(const char *url, char *file_name, size_t size);
void th_serve_sector_api(th_socket_t client, const TrivialHttpOptions *options,
  const HttpRequest *request, int route, const char *file_name);

#endif
