package com.duo.app.controller;

import com.duo.app.model.UserAccount;
import com.duo.app.service.AuthService;
import com.duo.app.service.AuthService.LoginCommand;
import com.duo.app.service.AuthService.SignUpCommand;
import com.duo.app.service.AuthValidationException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private static final String SESSION_USERNAME = "AUTH_USERNAME";

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/signup")
    public Map<String, Object> signUp(@RequestBody SignUpCommand command) {
        UserAccount account = authService.signUp(command);
        return userResponse(account, false);
    }

    @PostMapping("/login")
    public Map<String, Object> login(@RequestBody LoginCommand command, HttpServletRequest request) {
        UserAccount account = authService.login(command);
        HttpSession session = request.getSession(true);
        session.setAttribute(SESSION_USERNAME, account.username());
        if (command.remember()) {
            session.setMaxInactiveInterval(60 * 60 * 24 * 14);
        }
        return userResponse(account, true);
    }

    @PostMapping("/logout")
    public Map<String, Object> logout(HttpServletRequest request) {
        HttpSession session = request.getSession(false);
        if (session != null) {
            session.invalidate();
        }
        return Map.of("authenticated", false);
    }

    @GetMapping("/me")
    public Map<String, Object> me(HttpServletRequest request) {
        HttpSession session = request.getSession(false);
        if (session == null) {
            return Map.of("authenticated", false);
        }
        Object username = session.getAttribute(SESSION_USERNAME);
        if (!(username instanceof String currentUsername)) {
            return Map.of("authenticated", false);
        }
        return authService.findByUsername(currentUsername)
                .map(account -> userResponse(account, true))
                .orElseGet(() -> Map.of("authenticated", false));
    }

    @GetMapping("/check-username")
    public Map<String, Object> checkUsername(@RequestParam String username) {
        return Map.of("available", authService.isUsernameAvailable(username));
    }

    @GetMapping("/check-email")
    public Map<String, Object> checkEmail(@RequestParam String email) {
        return Map.of("available", authService.isEmailAvailable(email));
    }

    @ExceptionHandler(AuthValidationException.class)
    public ResponseEntity<Map<String, Object>> handleAuthValidation(AuthValidationException exception) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(Map.of(
                "field", exception.getField() == null ? "" : exception.getField(),
                "message", exception.getMessage()));
    }

    private Map<String, Object> userResponse(UserAccount account, boolean authenticated) {
        return Map.of(
                "authenticated", authenticated,
                "name", account.name(),
                "username", account.username(),
                "email", account.email());
    }
}
