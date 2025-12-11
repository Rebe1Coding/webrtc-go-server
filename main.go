package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/gorilla/websocket"
	"github.com/rs/cors"
)

// Configuration
const (
	SecretKey = "123"
	Port      = ":8000"
)

// Models
type LoginRequest struct {
	Username string `json:"username"`
}

type LoginResponse struct {
	Token string `json:"token"`
}

type SessionCreateRequest struct {
	TargetUsername string `json:"targetUsername"`
	Type           string `json:"type"` // "video" or "audio"
}

type Session struct {
	SessionID string    `json:"sessionId"`
	Caller    string    `json:"caller"`
	Target    string    `json:"target"`
	Status    string    `json:"status"`
	Type      string    `json:"type"`
	CreatedAt time.Time `json:"createdAt"`
}

type WebSocketMessage struct {
	Event string                 `json:"event"`
	Data  map[string]interface{} `json:"data"`
}

type Claims struct {
	Username string `json:"sub"`
	jwt.RegisteredClaims
}

// In-memory storage
var (
	sessions      = make(map[string]*Session)        // sessionId -> Session
	userSessions  = make(map[string]string)          // username -> sessionId
	wsConnections = make(map[string]*websocket.Conn) // username -> WebSocket
	mu            sync.RWMutex                       // Mutex for thread safety
	upgrader      = websocket.Upgrader{
		CheckOrigin: func(r *http.Request) bool { return true },
	}
)

// JWT Functions
func createToken(username string) (string, error) {
	claims := Claims{
		Username: username,
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(60 * time.Minute)),
		},
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString([]byte(SecretKey))
}

func verifyToken(tokenString string) (string, error) {
	token, err := jwt.ParseWithClaims(tokenString, &Claims{}, func(token *jwt.Token) (interface{}, error) {
		return []byte(SecretKey), nil
	})

	if err != nil {
		return "", err
	}

	if claims, ok := token.Claims.(*Claims); ok && token.Valid {
		return claims.Username, nil
	}

	return "", fmt.Errorf("invalid token")
}

// Middleware to verify JWT
func authMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		authHeader := r.Header.Get("Authorization")
		if authHeader == "" || len(authHeader) < 8 {
			http.Error(w, "Missing authorization header", http.StatusUnauthorized)
			return
		}

		tokenString := authHeader[7:] // Remove "Bearer "
		username, err := verifyToken(tokenString)
		if err != nil {
			http.Error(w, "Invalid token", http.StatusUnauthorized)
			return
		}

		// Add username to request context
		r.Header.Set("X-Username", username)
		next(w, r)
	}
}

// REST API Handlers

// POST /api/auth/login
func handleLogin(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req LoginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request", http.StatusBadRequest)
		return
	}

	if req.Username == "" {
		http.Error(w, "Username required", http.StatusBadRequest)
		return
	}

	token, err := createToken(req.Username)
	if err != nil {
		http.Error(w, "Failed to create token", http.StatusInternalServerError)
		return
	}

	log.Printf("User logged in: %s", req.Username)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(LoginResponse{Token: token})
}

// POST /api/session - Create new session
func handleCreateSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	username := r.Header.Get("X-Username")

	var req SessionCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request", http.StatusBadRequest)
		return
	}

	mu.Lock()
	defer mu.Unlock()

	// Check if user already has active session
	if _, exists := userSessions[username]; exists {
		http.Error(w, "Already in active session", http.StatusBadRequest)
		return
	}

	// Check if target is busy
	if _, exists := userSessions[req.TargetUsername]; exists {
		http.Error(w, "Target user is busy", http.StatusConflict)
		return
	}

	if req.TargetUsername == username {
		http.Error(w, "Cannot call yourself", http.StatusBadRequest)
		return
	}

	// Create session
	session := &Session{
		SessionID: uuid.New().String(),
		Caller:    username,
		Target:    req.TargetUsername,
		Status:    "pending",
		Type:      req.Type,
		CreatedAt: time.Now(),
	}

	sessions[session.SessionID] = session
	userSessions[username] = session.SessionID
	userSessions[req.TargetUsername] = session.SessionID

	log.Printf("Session created: %s -> %s", username, req.TargetUsername)

	// Notify target via WebSocket
	if conn, ok := wsConnections[req.TargetUsername]; ok {
		go func() {
			conn.WriteJSON(map[string]interface{}{
				"event": "session_updated",
				"data":  session,
			})
		}()
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(session)
}

// GET /api/session - Get current session
func handleGetSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	username := r.Header.Get("X-Username")

	mu.RLock()
	defer mu.RUnlock()

	sessionID, exists := userSessions[username]
	if !exists {
		http.Error(w, "No active session", http.StatusNotFound)
		return
	}

	session, exists := sessions[sessionID]
	if !exists {
		http.Error(w, "Session not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(session)
}

// POST /api/session/accept
func handleAcceptSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	username := r.Header.Get("X-Username")

	mu.Lock()
	defer mu.Unlock()

	sessionID, exists := userSessions[username]
	if !exists {
		http.Error(w, "No pending session", http.StatusNotFound)
		return
	}

	session, exists := sessions[sessionID]
	if !exists {
		http.Error(w, "Session not found", http.StatusNotFound)
		return
	}

	if session.Target != username {
		http.Error(w, "Only target can accept", http.StatusForbidden)
		return
	}

	if session.Status != "pending" {
		http.Error(w, "Session not pending", http.StatusBadRequest)
		return
	}

	// Update status
	session.Status = "active"

	log.Printf("Session accepted: %s", sessionID)

	// Notify caller
	if conn, ok := wsConnections[session.Caller]; ok {
		go func() {
			conn.WriteJSON(map[string]interface{}{
				"event": "session_updated",
				"data":  session,
			})
		}()
	}

	// Also notify target (acceptor)
	if conn, ok := wsConnections[session.Target]; ok {
		go func() {
			conn.WriteJSON(map[string]interface{}{
				"event": "session_updated",
				"data":  session,
			})
		}()
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(session)
}

// POST /api/session/decline
func handleDeclineSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	username := r.Header.Get("X-Username")

	mu.Lock()
	defer mu.Unlock()

	sessionID, exists := userSessions[username]
	if !exists {
		http.Error(w, "No pending session", http.StatusNotFound)
		return
	}

	session, exists := sessions[sessionID]
	if !exists {
		http.Error(w, "Session not found", http.StatusNotFound)
		return
	}

	if session.Target != username {
		http.Error(w, "Only target can decline", http.StatusForbidden)
		return
	}

	session.Status = "declined"

	log.Printf("Session declined: %s", sessionID)

	// Notify caller
	caller := session.Caller
	if conn, ok := wsConnections[caller]; ok {
		go func() {
			conn.WriteJSON(map[string]interface{}{
				"event": "session_updated",
				"data":  session,
			})
		}()
	}

	// Cleanup
	delete(userSessions, username)
	delete(userSessions, caller)
	delete(sessions, sessionID)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(session)
}

// DELETE /api/session - Cancel/end session
func handleCancelSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodDelete {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	username := r.Header.Get("X-Username")

	mu.Lock()
	defer mu.Unlock()

	sessionID, exists := userSessions[username]
	if !exists {
		http.Error(w, "No active session", http.StatusNotFound)
		return
	}

	session, exists := sessions[sessionID]
	if !exists {
		http.Error(w, "Session not found", http.StatusNotFound)
		return
	}

	session.Status = "cancelled"

	log.Printf("Session cancelled: %s", sessionID)

	// Notify other party
	otherUser := session.Target
	if session.Caller != username {
		otherUser = session.Caller
	}

	if conn, ok := wsConnections[otherUser]; ok {
		go func() {
			conn.WriteJSON(map[string]interface{}{
				"event": "session_updated",
				"data":  session,
			})
		}()
	}

	// Cleanup
	delete(userSessions, username)
	delete(userSessions, otherUser)
	delete(sessions, sessionID)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(session)
}

// WebSocket Handler
func handleWebSocket(w http.ResponseWriter, r *http.Request) {
	// Get token from query
	token := r.URL.Query().Get("token")
	if token == "" {
		http.Error(w, "Token required", http.StatusUnauthorized)
		return
	}

	username, err := verifyToken(token)
	if err != nil {
		http.Error(w, "Invalid token", http.StatusUnauthorized)
		return
	}

	// Upgrade to WebSocket
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket upgrade error: %v", err)
		return
	}
	defer conn.Close()

	// Store connection
	mu.Lock()
	wsConnections[username] = conn
	mu.Unlock()

	log.Printf("WebSocket connected: %s", username)

	// Handle messages
	for {
		var msg WebSocketMessage
		if err := conn.ReadJSON(&msg); err != nil {
			log.Printf("WebSocket read error for %s: %v", username, err)
			break
		}

		if msg.Event == "signal" {
			// Forward signal to other party
			mu.RLock()
			sessionID, exists := userSessions[username]
			if !exists {
				mu.RUnlock()
				continue
			}

			session, exists := sessions[sessionID]
			if !exists || session.Status != "active" {
				mu.RUnlock()
				continue
			}

			otherUser := session.Target
			if session.Target == username {
				otherUser = session.Caller
			}

			otherConn, exists := wsConnections[otherUser]
			mu.RUnlock()

			if exists {
				go func() {
					otherConn.WriteJSON(map[string]interface{}{
						"event": "signal",
						"data":  msg.Data,
					})
				}()
				log.Printf("Signal forwarded: %s -> %s", username, otherUser)
			}
		}
	}

	// Cleanup on disconnect
	mu.Lock()
	delete(wsConnections, username)

	// Cancel session if exists
	if sessionID, exists := userSessions[username]; exists {
		if session, exists := sessions[sessionID]; exists {
			session.Status = "disconnected"

			otherUser := session.Target
			if session.Target == username {
				otherUser = session.Caller
			}

			// Notify other user
			if otherConn, ok := wsConnections[otherUser]; ok {
				go func() {
					otherConn.WriteJSON(map[string]interface{}{
						"event": "session_updated",
						"data":  session,
					})
				}()
			}

			// Cleanup
			delete(userSessions, username)
			delete(userSessions, otherUser)
			delete(sessions, sessionID)
		}
	}
	mu.Unlock()

	log.Printf("WebSocket disconnected: %s", username)
}

// Root handler
func handleRoot(w http.ResponseWriter, r *http.Request) {
	response := map[string]interface{}{
		"name":    "WebRTC Signaling Server (Go)",
		"version": "1.0.0",
		"endpoints": map[string]string{
			"auth":      "/api/auth/login",
			"session":   "/api/session",
			"websocket": "/ws?token=YOUR_JWT_TOKEN",
		},
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

// Route handler to support REST-like routing
func handleSessionRoutes(w http.ResponseWriter, r *http.Request) {
	path := r.URL.Path

	switch path {
	case "/api/session":
		switch r.Method {
		case http.MethodPost:
			authMiddleware(handleCreateSession)(w, r)
		case http.MethodGet:
			authMiddleware(handleGetSession)(w, r)
		case http.MethodDelete:
			authMiddleware(handleCancelSession)(w, r)
		default:
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		}
	case "/api/session/accept":
		authMiddleware(handleAcceptSession)(w, r)
	case "/api/session/decline":
		authMiddleware(handleDeclineSession)(w, r)
	default:
		http.Error(w, "Not found", http.StatusNotFound)
	}
}

func main() {
	mux := http.NewServeMux()

	// Routes
	mux.HandleFunc("/", handleRoot)
	mux.HandleFunc("/api/auth/login", handleLogin)
	mux.HandleFunc("/api/session", handleSessionRoutes)
	mux.HandleFunc("/api/session/accept", handleSessionRoutes)
	mux.HandleFunc("/api/session/decline", handleSessionRoutes)
	mux.HandleFunc("/ws", handleWebSocket)

	// CORS middleware
	handler := cors.New(cors.Options{
		AllowedOrigins:   []string{"*"},
		AllowedMethods:   []string{"GET", "POST", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Authorization", "Content-Type"},
		AllowCredentials: true,
	}).Handler(mux)

	log.Printf("🚀 WebRTC Signaling Server starting on %s", Port)
	log.Printf("📡 WebSocket endpoint: ws://localhost%s/ws", Port)
	log.Fatal(http.ListenAndServe(Port, handler))
}
