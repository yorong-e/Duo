package com.duo.app.service;

import com.duo.app.model.UserAccount;
import com.duo.app.repository.UserRepository;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Optional;
import java.util.regex.Pattern;
import org.springframework.stereotype.Service;

@Service
public class AuthService {

    private static final Pattern USERNAME_PATTERN = Pattern.compile("^[A-Za-z0-9_]{4,20}$");
    private static final Pattern EMAIL_PATTERN = Pattern.compile("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$");
    private static final SecureRandom SECURE_RANDOM = new SecureRandom();

    private final UserRepository userRepository;

    public AuthService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    public UserAccount signUp(SignUpCommand command) {
        validateSignUp(command);

        String username = command.username().trim();
        String email = command.email().trim();

        if (userRepository.existsByUsername(username)) {
            throw new AuthValidationException("username", "이미 사용 중인 아이디입니다.");
        }
        if (userRepository.existsByEmail(email)) {
            throw new AuthValidationException("email", "이미 사용 중인 이메일입니다.");
        }

        String salt = createSalt();
        UserAccount account = new UserAccount(
                0,
                command.name().trim(),
                username,
                email,
                hashPassword(command.password(), salt),
                salt);

        return userRepository.save(account);
    }

    public UserAccount login(LoginCommand command) {
        String username = command.username() == null ? "" : command.username().trim();
        String password = command.password() == null ? "" : command.password();
        if (username.isBlank()) {
            throw new AuthValidationException("username", "아이디를 입력해주세요.");
        }
        if (password.isBlank()) {
            throw new AuthValidationException("password", "비밀번호를 입력해주세요.");
        }

        UserAccount account = userRepository.findByUsername(username).orElse(null);
        if (account == null || !account.passwordHash().equals(hashPassword(password, account.passwordSalt()))) {
            throw new AuthValidationException(null, "아이디 또는 비밀번호가 올바르지 않습니다.");
        }
        return account;
    }

    public boolean isUsernameAvailable(String username) {
        String normalized = username == null ? "" : username.trim();
        return !normalized.isBlank() && !userRepository.existsByUsername(normalized);
    }

    public boolean isEmailAvailable(String email) {
        String normalized = email == null ? "" : email.trim();
        return !normalized.isBlank() && !userRepository.existsByEmail(normalized);
    }

    public Optional<UserAccount> findByUsername(String username) {
        return userRepository.findByUsername(username == null ? "" : username.trim());
    }

    private void validateSignUp(SignUpCommand command) {
        String name = command.name() == null ? "" : command.name().trim();
        String username = command.username() == null ? "" : command.username().trim();
        String email = command.email() == null ? "" : command.email().trim();
        String password = command.password() == null ? "" : command.password();
        String confirmPassword = command.confirmPassword() == null ? "" : command.confirmPassword();

        if (name.isBlank()) {
            throw new AuthValidationException("name", "이름을 입력해주세요.");
        }
        if (!USERNAME_PATTERN.matcher(username).matches()) {
            throw new AuthValidationException("username", "아이디는 영문, 숫자, 밑줄 4~20자로 입력해주세요.");
        }
        if (!EMAIL_PATTERN.matcher(email).matches()) {
            throw new AuthValidationException("email", "올바른 이메일 형식으로 입력해주세요.");
        }
        if (password.length() < 8 || !password.matches(".*[A-Za-z].*") || !password.matches(".*[0-9].*")) {
            throw new AuthValidationException("password", "비밀번호는 8자 이상이며 영문과 숫자를 포함해야 합니다.");
        }
        if (!password.equals(confirmPassword)) {
            throw new AuthValidationException("confirmPassword", "비밀번호가 일치하지 않습니다.");
        }
    }

    private String createSalt() {
        byte[] bytes = new byte[16];
        SECURE_RANDOM.nextBytes(bytes);
        return Base64.getEncoder().encodeToString(bytes);
    }

    private String hashPassword(String password, String salt) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest((salt + ":" + password).getBytes(StandardCharsets.UTF_8));
            return Base64.getEncoder().encodeToString(hash);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        }
    }

    public record SignUpCommand(String name, String username, String email, String password, String confirmPassword) {
    }

    public record LoginCommand(String username, String password, boolean remember) {
    }
}
