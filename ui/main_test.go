package main

import (
	"bufio"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"testing/fstest"
	"time"
)

func testFiles() fstest.MapFS {
	return fstest.MapFS{"index.html": &fstest.MapFile{Data: []byte("<html>wiki UI</html>")}, "assets/app-abc.js": &fstest.MapFile{Data: []byte("console.log('app')")}}
}
func TestProxyPreservesAuthorizationAndSeparatesServices(t *testing.T) {
	seen := make(chan string, 2)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen <- r.URL.RequestURI()
		if r.Header.Get("Authorization") != "Bearer user-token" {
			t.Error("caller token lost")
		}
		if r.Header.Get("Cookie") != "" || r.Header.Get("Forwarded") != "" || r.Header.Get("X-Forwarded-Host") != "" {
			t.Error("untrusted browser headers forwarded")
		}
		w.Header().Set("Set-Cookie", "upstream=private")
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer backend.Close()
	h, err := handler(testFiles(), backend.URL, backend.URL)
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range []struct{ input, want string }{{"/api/v1/pages?q=test", "/api/v1/pages?q=test"}, {"/agent-api/chat/sessions", "/chat/sessions"}} {
		req := httptest.NewRequest("GET", p.input, nil)
		req.Header.Set("Authorization", "Bearer user-token")
		req.Header.Set("Cookie", "secret=cookie")
		req.Header.Set("Forwarded", "host=attacker")
		req.Header.Set("X-Forwarded-Host", "attacker")
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != 200 || <-seen != p.want {
			t.Fatalf("wrong proxy response: %d", out.Code)
		}
		if out.Header().Get("Cache-Control") != "no-store" || out.Header().Get("Set-Cookie") != "" {
			t.Fatal("private response cached or cookie leaked")
		}
	}
}
func TestSPAAndPrivateEndpoints(t *testing.T) {
	h, _ := handler(testFiles(), "http://127.0.0.1:1", "http://127.0.0.1:1")
	for _, p := range []struct {
		path, method, token string
		status              int
	}{{"/pages/rule-one", "GET", "", 200}, {"/assets/missing.js", "GET", "", 404}, {"/api/v1/pages", "GET", "", 401}, {"/agent-api/jobs", "POST", "", 401}, {"/api/v1/pages", "GET", "Bearer x", 502}, {"/agent-api/jobs", "TRACE", "Bearer x", 405}, {"/healthz", "GET", "", 200}} {
		r := httptest.NewRequest(p.method, p.path, nil)
		r.Header.Set("Authorization", p.token)
		out := httptest.NewRecorder()
		h.ServeHTTP(out, r)
		if out.Code != p.status {
			t.Errorf("%s: %d instead of %d", p.path, out.Code, p.status)
		}
		if out.Header().Get("Content-Security-Policy") == "" {
			t.Error("missing CSP")
		}
	}
}

type watchedBody struct{ read bool }

func (b *watchedBody) Read([]byte) (int, error) { b.read = true; return 0, io.EOF }
func (b *watchedBody) Close() error             { return nil }
func TestRejectsUnauthenticatedBodyWithoutReading(t *testing.T) {
	h, _ := handler(testFiles(), "http://127.0.0.1:1", "http://127.0.0.1:1")
	body := &watchedBody{}
	r := httptest.NewRequest("POST", "/api/v1/raw", nil)
	r.Body = body
	r.ContentLength = 1024 * 1024 * 1024
	out := httptest.NewRecorder()
	h.ServeHTTP(out, r)
	if out.Code != 401 || body.read {
		t.Fatal("request body read before checking credentials")
	}
}
func TestSSEIsFlushedBeforeResponseCompletes(t *testing.T) {
	finish := make(chan struct{})
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("event: status\ndata: {\"status\":\"planning\"}\n\n"))
		w.(http.Flusher).Flush()
		<-finish
		_, _ = w.Write([]byte("event: message\ndata: {}\n\n"))
	}))
	defer backend.Close()
	h, _ := handler(testFiles(), backend.URL, backend.URL)
	server := httptest.NewServer(h)
	defer server.Close()
	done := make(chan error, 1)
	go func() {
		r, _ := http.NewRequest("POST", server.URL+"/agent-api/chat/sessions/one/messages", strings.NewReader(`{"text":"hello"}`))
		r.Header.Set("Authorization", "Bearer token")
		response, err := server.Client().Do(r)
		if err != nil {
			done <- err
			return
		}
		defer response.Body.Close()
		_, err = bufio.NewReader(response.Body).ReadString('\n')
		done <- err
	}()
	select {
	case err := <-done:
		close(finish)
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		close(finish)
		t.Fatal("SSE was buffered")
	}
}
func TestInvalidUpstreamIsRejected(t *testing.T) {
	for _, target := range []string{"file:///etc/passwd", "http://user:password@localhost", "http://localhost/path", "http://localhost?x=1"} {
		if _, err := upstream(target, ""); err == nil {
			t.Fatalf("accepted %s", target)
		}
	}
}
