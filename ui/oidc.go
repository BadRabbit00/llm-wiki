package main

import (
	"bytes"
	"context"
	"crypto"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/coreos/go-oidc/v3/oidc"
	"github.com/go-jose/go-jose/v4"
	"golang.org/x/oauth2"
)

const sessionCookie = "wiki_session"
const flowCookie = "wiki_oidc_flow"

type oidcConfig struct {
	Issuer, ClientID, SecretFile, RedirectURL, SessionTokenFile string
	InsecureHTTP, CookieSecure                                  bool
}

func oidcEnvironment() oidcConfig {
	return oidcConfig{
		Issuer: os.Getenv("WIKI_UI_OIDC_ISSUER"), ClientID: os.Getenv("WIKI_UI_OIDC_CLIENT_ID"),
		SecretFile: os.Getenv("WIKI_UI_OIDC_SECRET_FILE"), RedirectURL: os.Getenv("WIKI_UI_OIDC_REDIRECT_URL"),
		SessionTokenFile: os.Getenv("WIKI_UI_SESSION_TOKEN_FILE"),
		InsecureHTTP:     os.Getenv("WIKI_UI_OIDC_INSECURE_HTTP") == "1", CookieSecure: env("WIKI_UI_COOKIE_SECURE", "1") == "1",
	}
}

func loopback(host string) bool {
	return host == "localhost" || net.ParseIP(host).IsLoopback()
}

func readSecret(path string) (string, error) {
	if path == "" {
		return "", errors.New("OIDC requires configured, readable secret files")
	}
	file, err := os.Open(path)
	if err != nil {
		return "", errors.New("OIDC requires configured, readable secret files")
	}
	defer file.Close()
	body, err := io.ReadAll(io.LimitReader(file, 8193))
	if err != nil || len(body) > 8192 || len(bytes.TrimSpace(body)) == 0 {
		return "", errors.New("OIDC secret file is empty or invalid")
	}
	return string(bytes.TrimSpace(body)), nil
}

func oidcHTTPClient() *http.Client {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	transport.DialContext = (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext
	transport.TLSHandshakeTimeout = 5 * time.Second
	transport.ResponseHeaderTimeout = 10 * time.Second
	return &http.Client{Transport: transport, Timeout: 10 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

type oidcFlow struct {
	nonce, verifier string
	expires         time.Time
}
type providerInfo struct {
	oauth        oauth2.Config
	jwks, logout string
}
type oidcAuth struct {
	config                                     oidcConfig
	client                                     *http.Client
	wikiURL, issuerToken, clientSecret, origin string
	mu                                         sync.Mutex
	provider                                   *providerInfo
	flows                                      map[string]oidcFlow
	keys                                       *oidc.StaticKeySet
	cancel                                     context.CancelFunc
}
type oidcContextKey struct{}

func newOIDC(config oidcConfig, wikiURL string) (*oidcAuth, error) {
	issuer, err := url.Parse(config.Issuer)
	if err != nil || issuer.Host == "" || issuer.User != nil || issuer.RawQuery != "" || issuer.Fragment != "" ||
		(issuer.Scheme != "https" && !(issuer.Scheme == "http" && config.InsecureHTTP && loopback(issuer.Hostname()))) {
		return nil, errors.New("set WIKI_UI_OIDC_ISSUER to an HTTPS issuer (HTTP is allowed only for an explicit local test)")
	}
	redirect, err := url.Parse(config.RedirectURL)
	if err != nil || redirect.Host == "" || redirect.User != nil || redirect.RawQuery != "" || redirect.Fragment != "" || redirect.Path != "/auth/callback" ||
		(redirect.Scheme != "https" && !(redirect.Scheme == "http" && loopback(redirect.Hostname()))) {
		return nil, errors.New("set WIKI_UI_OIDC_REDIRECT_URL to the browser's /auth/callback address")
	}
	if config.ClientID == "" {
		return nil, errors.New("set WIKI_UI_OIDC_CLIENT_ID")
	}
	if !config.CookieSecure && !(config.InsecureHTTP && loopback(redirect.Hostname())) {
		return nil, errors.New("WIKI_UI_COOKIE_SECURE must be 1 outside a local test")
	}
	secret, err := readSecret(config.SecretFile)
	if err != nil {
		return nil, err
	}
	token, err := readSecret(config.SessionTokenFile)
	if err != nil {
		return nil, err
	}
	if _, err := upstream(wikiURL, ""); err != nil {
		return nil, err
	}
	ctx, cancel := context.WithCancel(context.Background())
	a := &oidcAuth{config: config, client: oidcHTTPClient(), wikiURL: strings.TrimRight(wikiURL, "/"),
		issuerToken: token, clientSecret: secret, origin: redirect.Scheme + "://" + redirect.Host,
		flows: make(map[string]oidcFlow), cancel: cancel}
	go a.refreshLoop(ctx)
	return a, nil
}

func (a *oidcAuth) close() { a.cancel(); a.client.CloseIdleConnections() }

func (a *oidcAuth) endpointAllowed(address string) bool {
	issuer, _ := url.Parse(a.config.Issuer)
	u, err := url.Parse(address)
	return err == nil && u.Host == issuer.Host && u.Scheme == issuer.Scheme && u.User == nil && u.Fragment == ""
}

func (a *oidcAuth) discovery(ctx context.Context, fresh bool) (*providerInfo, error) {
	a.mu.Lock()
	cached := a.provider
	a.mu.Unlock()
	if cached != nil && !fresh {
		return cached, nil
	}
	provider, err := oidc.NewProvider(oidc.ClientContext(ctx, a.client), a.config.Issuer)
	if err != nil {
		return nil, errors.New("OIDC discovery unavailable")
	}
	var metadata struct {
		JWKS   string `json:"jwks_uri"`
		Logout string `json:"end_session_endpoint"`
	}
	if err := provider.Claims(&metadata); err != nil {
		return nil, errors.New("invalid OIDC discovery")
	}
	endpoint := provider.Endpoint()
	if !a.endpointAllowed(endpoint.AuthURL) || !a.endpointAllowed(endpoint.TokenURL) || !a.endpointAllowed(metadata.JWKS) ||
		(metadata.Logout != "" && !a.endpointAllowed(metadata.Logout)) {
		return nil, errors.New("OIDC endpoints must belong to the issuer origin")
	}
	endpoint.AuthStyle = oauth2.AuthStyleInParams
	info := &providerInfo{oauth: oauth2.Config{ClientID: a.config.ClientID, ClientSecret: a.clientSecret,
		Endpoint: endpoint, RedirectURL: a.config.RedirectURL, Scopes: []string{oidc.ScopeOpenID, "profile", "email", "groups"}},
		jwks: metadata.JWKS, logout: metadata.Logout}
	a.mu.Lock()
	a.provider = info
	a.mu.Unlock()
	return info, nil
}

func (a *oidcAuth) refreshKeys(ctx context.Context, info *providerInfo) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, info.jwks, nil)
	if err != nil {
		return err
	}
	response, err := a.client.Do(req)
	if err != nil {
		return errors.New("OIDC keys unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return errors.New("OIDC keys unavailable")
	}
	var keys jose.JSONWebKeySet
	if err := json.NewDecoder(io.LimitReader(response.Body, 1024*1024)).Decode(&keys); err != nil {
		return errors.New("invalid OIDC keys")
	}
	public := []crypto.PublicKey{}
	for _, key := range keys.Keys {
		if key.Valid() && key.IsPublic() && (key.Use == "" || key.Use == "sig") && (key.Algorithm == "" || key.Algorithm == "RS256") {
			public = append(public, key.Key)
		}
	}
	if len(public) == 0 {
		return errors.New("OIDC has no signing keys")
	}
	a.mu.Lock()
	a.keys = &oidc.StaticKeySet{PublicKeys: public}
	a.mu.Unlock()
	return nil
}

// VerifySignature implements oidc.KeySet. Claim and algorithm checks remain in IDTokenVerifier.
func (a *oidcAuth) VerifySignature(ctx context.Context, token string) ([]byte, error) {
	a.mu.Lock()
	keys := a.keys
	info := a.provider
	a.mu.Unlock()
	if keys != nil {
		if payload, err := keys.VerifySignature(ctx, token); err == nil {
			return payload, nil
		}
	}
	if info == nil {
		return nil, errors.New("OIDC provider is not initialized")
	}
	if err := a.refreshKeys(ctx, info); err != nil {
		return nil, err
	}
	a.mu.Lock()
	keys = a.keys
	a.mu.Unlock()
	return keys.VerifySignature(ctx, token)
}

func (a *oidcAuth) refreshLoop(ctx context.Context) {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			a.mu.Lock()
			info := a.provider
			for state, flow := range a.flows {
				if !flow.expires.After(now) {
					delete(a.flows, state)
				}
			}
			a.mu.Unlock()
			if info != nil {
				refresh, cancel := context.WithTimeout(ctx, 10*time.Second)
				// Keep the last valid keys on outage; existing wiki sessions never use IdP.
				_ = a.refreshKeys(refresh, info)
				cancel()
			}
		}
	}
}

func randomSecret() string {
	value := make([]byte, 32)
	_, _ = rand.Read(value) // crypto/rand.Read either fills the buffer or terminates the process.
	return base64.RawURLEncoding.EncodeToString(value)
}

func (a *oidcAuth) cookie(name, value, path string, expires time.Time) *http.Cookie {
	return &http.Cookie{Name: name, Value: value, Path: path, HttpOnly: true, Secure: a.config.CookieSecure,
		SameSite: http.SameSiteLaxMode, Expires: expires}
}

func (a *oidcAuth) expiredCookie() *http.Cookie {
	cookie := a.cookie(sessionCookie, "", "/", time.Unix(1, 0))
	cookie.MaxAge = -1
	return cookie
}

func (a *oidcAuth) login(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	info, err := a.discovery(ctx, true)
	if err != nil {
		http.Error(w, "Вход временно недоступен: нет связи с Authentik.", http.StatusServiceUnavailable)
		return
	}
	state := randomSecret()
	flow := oidcFlow{nonce: randomSecret(), verifier: oauth2.GenerateVerifier(), expires: time.Now().Add(10 * time.Minute)}
	a.mu.Lock()
	for key, pending := range a.flows {
		if !pending.expires.After(time.Now()) {
			delete(a.flows, key)
		}
	}
	if len(a.flows) >= 10000 {
		a.mu.Unlock()
		http.Error(w, "Вход временно занят. Повторите позже.", 503)
		return
	}
	a.flows[state] = flow
	a.mu.Unlock()
	http.SetCookie(w, a.cookie(flowCookie, state, "/auth", flow.expires))
	http.Redirect(w, r, info.oauth.AuthCodeURL(state, oidc.Nonce(flow.nonce), oauth2.S256ChallengeOption(flow.verifier)), http.StatusFound)
}

func (a *oidcAuth) callback(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	state := r.URL.Query().Get("state")
	binding, err := r.Cookie(flowCookie)
	if err != nil || state == "" || subtle.ConstantTimeCompare([]byte(binding.Value), []byte(state)) != 1 {
		http.Error(w, "Недействительное состояние входа.", 400)
		return
	}
	a.mu.Lock()
	flow, found := a.flows[state]
	delete(a.flows, state)
	a.mu.Unlock()
	if !found || !flow.expires.After(time.Now()) {
		http.Error(w, "Срок входа истёк. Начните заново.", 400)
		return
	}
	clear := a.cookie(flowCookie, "", "/auth", time.Unix(1, 0))
	clear.MaxAge = -1
	http.SetCookie(w, clear)
	if r.URL.Query().Get("error") != "" || r.URL.Query().Get("code") == "" {
		http.Error(w, "Вход не подтверждён.", 400)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	info, err := a.discovery(ctx, false)
	if err != nil {
		http.Error(w, "Вход временно недоступен.", 503)
		return
	}
	oauthToken, err := info.oauth.Exchange(oidc.ClientContext(ctx, a.client), r.URL.Query().Get("code"), oauth2.VerifierOption(flow.verifier))
	if err != nil {
		http.Error(w, "Не удалось подтвердить вход.", 400)
		return
	}
	rawID, ok := oauthToken.Extra("id_token").(string)
	if !ok {
		http.Error(w, "Authentik не вернул ID-token.", 400)
		return
	}
	verified, err := oidc.NewVerifier(a.config.Issuer, a, &oidc.Config{ClientID: a.config.ClientID}).Verify(ctx, rawID)
	if err != nil || verified.IssuedAt.IsZero() || verified.IssuedAt.After(time.Now().Add(60*time.Second)) ||
		verified.Expiry.Before(verified.IssuedAt) || subtle.ConstantTimeCompare([]byte(verified.Nonce), []byte(flow.nonce)) != 1 {
		http.Error(w, "Недействительное подтверждение личности.", 400)
		return
	}
	var claims struct {
		Subject   string   `json:"sub"`
		Username  string   `json:"preferred_username"`
		Groups    []string `json:"groups"`
		NotBefore int64    `json:"nbf"`
	}
	if err := verified.Claims(&claims); err != nil || claims.Subject == "" || claims.NotBefore > time.Now().Add(60*time.Second).Unix() {
		http.Error(w, "Некорректные данные пользователя.", 400)
		return
	}
	body, _ := json.Marshal(map[string]any{"subject": claims.Subject, "username": claims.Username, "groups": claims.Groups})
	// Missing groups must be an empty list, not JSON null, for the strict API model.
	if claims.Groups == nil {
		body, _ = json.Marshal(map[string]any{"subject": claims.Subject, "username": claims.Username, "groups": []string{}})
	}
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, a.wikiURL+"/api/v1/sessions", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+a.issuerToken)
	req.Header.Set("Content-Type", "application/json")
	response, err := a.client.Do(req)
	if err != nil {
		http.Error(w, "Не удалось создать сеанс вики.", 503)
		return
	}
	defer response.Body.Close()
	var session struct {
		Token   string    `json:"token"`
		Expires time.Time `json:"expires_at"`
	}
	if response.StatusCode != 200 || json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&session) != nil ||
		session.Token == "" || !session.Expires.After(time.Now()) {
		http.Error(w, "Не удалось создать сеанс вики.", 503)
		return
	}
	http.SetCookie(w, a.cookie(sessionCookie, session.Token, "/", session.Expires))
	http.Redirect(w, r, "/", http.StatusFound)
}

func (a *oidcAuth) logout(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	if r.Header.Get("Origin") != a.origin {
		http.Error(w, "Недопустимый источник запроса.", 403)
		return
	}
	http.SetCookie(w, a.expiredCookie())
	if cookie, err := r.Cookie(sessionCookie); err == nil && cookie.Value != "" {
		ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
		defer cancel()
		req, _ := http.NewRequestWithContext(ctx, http.MethodDelete, a.wikiURL+"/api/v1/sessions/current", nil)
		req.Header.Set("Authorization", "Bearer "+cookie.Value)
		response, err := a.client.Do(req)
		if err != nil {
			http.Error(w, "Cookie удалён, но отзыв сеанса не подтверждён. Повторите после восстановления вики.", 503)
			return
		}
		response.Body.Close()
		if response.StatusCode != 204 && response.StatusCode != 401 {
			http.Error(w, "Cookie удалён, но отзыв сеанса не подтверждён.", 503)
			return
		}
	}
	// Do not fetch discovery during logout: an unavailable IdP must not delay local revocation.
	a.mu.Lock()
	info := a.provider
	a.mu.Unlock()
	if info != nil && info.logout != "" {
		address, _ := url.Parse(info.logout)
		query := address.Query()
		query.Set("client_id", a.config.ClientID)
		query.Set("post_logout_redirect_uri", a.origin+"/")
		address.RawQuery = query.Encode()
		http.Redirect(w, r, address.String(), http.StatusSeeOther)
		return
	}
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = w.Write([]byte("Вы вышли из вики. Для нового входа откройте /auth/login."))
}

func (a *oidcAuth) protect(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Referrer-Policy", "no-referrer")
		switch r.URL.Path {
		case "/auth/login":
			a.login(w, r)
			return
		case "/auth/callback":
			a.callback(w, r)
			return
		case "/auth/logout", "/logout":
			a.logout(w, r)
			return
		case "/healthz":
			next.ServeHTTP(w, r)
			return
		}
		if strings.HasPrefix(r.URL.Path, "/assets/") {
			next.ServeHTTP(w, r)
			return
		}
		// Only the server's callback may receive the plaintext session response.
		if strings.TrimRight(r.URL.Path, "/") == "/api/v1/sessions" {
			http.Error(w, "Недоступно через UI.", 403)
			return
		}
		cookie, err := r.Cookie(sessionCookie)
		if err != nil || cookie.Value == "" {
			if r.Method == http.MethodGet {
				a.login(w, r)
			} else {
				http.Redirect(w, r, "/auth/login", http.StatusSeeOther)
			}
			return
		}
		if r.Method != http.MethodGet && r.Method != http.MethodHead && r.Header.Get("Origin") != a.origin {
			http.Error(w, "Недопустимый источник запроса.", 403)
			return
		}
		request := r.Clone(context.WithValue(r.Context(), oidcContextKey{}, a))
		request.Header.Set("Authorization", "Bearer "+cookie.Value)
		next.ServeHTTP(w, request)
	})
}
