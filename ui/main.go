package main

import (
	"context"
	"embed"
	"encoding/json"
	"errors"
	"io/fs"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"path"
	"strings"
	"syscall"
	"time"
)

//go:embed all:dist
var assets embed.FS

func env(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func apiError(w http.ResponseWriter, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]string{"code": code, "message": message}})
}

func upstream(address, prefix string) (http.Handler, error) {
	target, err := url.Parse(address)
	if err != nil || target.Host == "" || (target.Scheme != "http" && target.Scheme != "https") || target.User != nil || target.RawQuery != "" || target.Fragment != "" || (target.Path != "" && target.Path != "/") {
		return nil, errors.New("upstream must be an HTTP(S) origin without credentials, path or query")
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	transport.ResponseHeaderTimeout = 5 * time.Minute
	proxy := &httputil.ReverseProxy{
		Transport:     transport,
		FlushInterval: -1, // Deliver every SSE event immediately.
		Rewrite: func(r *httputil.ProxyRequest) {
			r.Out.URL.Path = strings.TrimPrefix(r.In.URL.Path, prefix)
			r.Out.URL.RawPath = ""
			r.SetURL(target)
			r.Out.Header.Del("Cookie")
			r.Out.Header.Del("Origin")
			r.Out.Header.Del("Referer")
		},
		ModifyResponse: func(r *http.Response) error {
			r.Header.Del("Set-Cookie")
			r.Header.Set("Cache-Control", "no-store")
			r.Header.Set("X-Accel-Buffering", "no")
			return nil
		},
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			apiError(w, http.StatusBadGateway, "E_SERVICE_UNAVAILABLE", "Сервис временно недоступен. Повторите запрос позже.")
		},
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasPrefix(strings.ToLower(r.Header.Get("Authorization")), "bearer ") || strings.TrimSpace(r.Header.Get("Authorization")[7:]) == "" {
			apiError(w, http.StatusUnauthorized, "E_UNAUTHORIZED", "Войдите с помощью токена доступа.")
			return
		}
		switch r.Method {
		case "GET", "HEAD", "POST", "PUT", "PATCH", "DELETE":
		default:
			apiError(w, http.StatusMethodNotAllowed, "E_METHOD", "Метод не поддерживается.")
			return
		}
		limit := int64(1024 * 1024)
		if r.Method == "POST" && strings.TrimRight(r.URL.Path, "/") == "/api/v1/raw" {
			limit = 1024*1024*1024 + 65536 // Actual configured upload limit is enforced by wikisvc.
		}
		if r.ContentLength > limit {
			apiError(w, http.StatusRequestEntityTooLarge, "E_BODY_TOO_LARGE", "Файл или сообщение слишком большие.")
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, limit)
		proxy.ServeHTTP(w, r)
	}), nil
}

func handler(files fs.FS, wikiURL, agentURL string) (http.Handler, error) {
	wiki, err := upstream(wikiURL, "")
	if err != nil {
		return nil, err
	}
	agent, err := upstream(agentURL, "/agent-api")
	if err != nil {
		return nil, err
	}
	fileServer := http.FileServerFS(files)
	mux := http.NewServeMux()
	mux.Handle("/api/v1/", wiki)
	mux.Handle("/agent-api/", agent)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok","service":"wiki-ui"}`))
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" && r.Method != "HEAD" {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		name := strings.TrimPrefix(path.Clean(r.URL.Path), "/")
		if strings.HasPrefix(name, ".") || strings.HasPrefix(name, "api/") || strings.HasPrefix(name, "agent-api/") {
			http.NotFound(w, r)
			return
		}
		if info, err := fs.Stat(files, name); err == nil && !info.IsDir() {
			if strings.HasPrefix(name, "assets/") {
				w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
			}
			fileServer.ServeHTTP(w, r)
			return
		}
		if path.Ext(name) != "" {
			http.NotFound(w, r)
			return
		}
		index, err := fs.ReadFile(files, "index.html")
		if err != nil {
			apiError(w, http.StatusServiceUnavailable, "E_UI_BUILD", "Интерфейс не собран: выполните npm ci && npm run build в ui/.")
			return
		}
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		if r.Method != "HEAD" {
			_, _ = w.Write(index)
		}
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "same-origin")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'")
		mux.ServeHTTP(w, r)
	}), nil
}

func main() {
	files, _ := fs.Sub(assets, "dist")
	h, err := handler(files, env("WIKI_UI_WIKISVC_URL", "http://127.0.0.1:8787"), env("WIKI_UI_AGENT_URL", "http://127.0.0.1:8788"))
	if err != nil {
		log.Fatal(err)
	}
	server := &http.Server{Addr: env("WIKI_UI_BIND", "127.0.0.1:8789"), Handler: h, ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 5 * time.Minute, IdleTimeout: 90 * time.Second}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Printf("wiki UI listening on %s", server.Addr)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}
