#include "trivialhttp.h"

static void print_usage(const char *program) {
  printf("TrivialHTTP %s\n", TH_VERSION);
  printf("Usage: %s [options]\n\n", program);
  printf("  --root PATH   Folder to serve. Default: current directory.\n");
  printf("  --port PORT   Local port. Default: 0 (choose a free port).\n");
  printf("  --open PATH   Browser target. Default: /.\n");
  printf("  --no-open     Do not open the default browser.\n");
  printf("  --once        Serve one request, then exit.\n");
  printf("  --help        Show this help.\n\n");
  printf("County Field Map classification is stored under project-data/sectors relative to --root.\n");
}

static int parse_port(const char *value, unsigned short *port_out) {
  char *end = NULL;
  long parsed = strtol(value, &end, 10);
  if (!value[0] || *end || parsed < 0 || parsed > 65535) return -1;
  *port_out = (unsigned short)parsed;
  return 0;
}

static int parse_args(int argc, char **argv, TrivialHttpOptions *options) {
  memset(options, 0, sizeof(*options));
  th_strlcpy(options->root, ".", sizeof(options->root));
  th_strlcpy(options->open_target, "/", sizeof(options->open_target));
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "--help") || !strcmp(argv[i], "-h")) {
      print_usage(argv[0]);
      return 1;
    } else if (!strcmp(argv[i], "--root")) {
      if (++i >= argc || th_strlcpy(options->root, argv[i], sizeof(options->root))) return -1;
    } else if (!strcmp(argv[i], "--port")) {
      if (++i >= argc || parse_port(argv[i], &options->port)) return -1;
    } else if (!strcmp(argv[i], "--open")) {
      if (++i >= argc || th_strlcpy(options->open_target, argv[i], sizeof(options->open_target))) return -1;
    } else if (!strcmp(argv[i], "--no-open")) {
      options->no_open = 1;
    } else if (!strcmp(argv[i], "--once")) {
      options->once = 1;
    } else {
      fprintf(stderr, "Unknown option: %s\n", argv[i]);
      return -1;
    }
  }
  return 0;
}

static void build_browser_url(unsigned short port, const char *target, char *url, size_t size) {
  if (!strncmp(target, "http://", 7) || !strncmp(target, "https://", 8))
    th_strlcpy(url, target, size);
  else
    snprintf(url, size, "http://127.0.0.1:%u%s%s", port, target[0] == '/' ? "" : "/", target);
}

int main(int argc, char **argv) {
  TrivialHttpOptions options;
  int parsed = parse_args(argc, argv, &options);
  if (parsed > 0) return 0;
  if (parsed < 0) return 2;
  if (th_canonical_path(options.root, options.root_real, sizeof(options.root_real))) {
    fprintf(stderr, "Could not resolve root folder: %s\n", options.root);
    return 2;
  }
  if (th_initialize_sockets()) {
    fprintf(stderr, "Could not initialize sockets.\n");
    return 2;
  }
  unsigned short port = 0;
  th_socket_t listener = th_create_listener(options.port, &port);
  if (listener == TH_INVALID_SOCKET) {
    fprintf(stderr, "Could not bind 127.0.0.1:%u.\n", options.port);
    th_shutdown_sockets();
    return 2;
  }
  char url[TH_URL_BUF];
  build_browser_url(port, options.open_target, url, sizeof(url));
  printf("TrivialHTTP %s\nRoot: %s\nURL: %s\nBind: 127.0.0.1:%u\n",
    TH_VERSION, options.root_real, url, port);
  printf("Classification storage: %s/%s\nPress Ctrl+C to stop.\n",
    TH_STORAGE_PARENT, TH_STORAGE_CHILD);
  fflush(stdout);
  if (!options.no_open) th_open_browser(url);
  for (;;) {
    struct sockaddr_in client_address;
    TH_SOCKLEN client_length = sizeof(client_address);
    th_socket_t client = accept(listener, (struct sockaddr *)&client_address, &client_length);
    if (client == TH_INVALID_SOCKET) continue;
    th_handle_client(client, &options);
    TH_CLOSE(client);
    if (options.once) break;
  }
  TH_CLOSE(listener);
  th_shutdown_sockets();
  return 0;
}
