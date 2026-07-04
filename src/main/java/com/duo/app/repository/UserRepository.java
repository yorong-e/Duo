package com.duo.app.repository;

import com.duo.app.model.UserAccount;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class UserRepository {

    private static final String PASSWORD_DELIMITER = ":";

    private final JdbcTemplate jdbcTemplate;

    public UserRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public UserAccount save(UserAccount user) {
        String password = user.passwordSalt() + PASSWORD_DELIMITER + user.passwordHash();
        KeyHolder keyHolder = new GeneratedKeyHolder();

        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement(
                    "INSERT INTO users(name, user_id, email, password) VALUES (?, ?, ?, ?)",
                    Statement.RETURN_GENERATED_KEYS);
            ps.setString(1, user.name());
            ps.setString(2, user.username());
            ps.setString(3, user.email());
            ps.setString(4, password);
            return ps;
        }, keyHolder);

        Number key = keyHolder.getKey();
        long generatedId = key == null ? 0 : key.longValue();
        return new UserAccount(
                generatedId,
                user.name(),
                user.username(),
                user.email(),
                user.passwordHash(),
                user.passwordSalt());
    }

    public Optional<UserAccount> findByUsername(String username) {
        List<UserAccount> results = jdbcTemplate.query(
                "SELECT id, name, user_id, email, password FROM users WHERE user_id = ?",
                this::mapRow,
                username);
        return results.stream().findFirst();
    }

    public boolean existsByUsername(String username) {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM users WHERE user_id = ?",
                Integer.class,
                username);
        return count != null && count > 0;
    }

    public boolean existsByEmail(String email) {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM users WHERE email = ?",
                Integer.class,
                email);
        return count != null && count > 0;
    }

    private UserAccount mapRow(ResultSet rs, int rowNum) throws SQLException {
        String storedPassword = rs.getString("password");
        String salt = "";
        String hash = storedPassword;
        int delimiterIndex = storedPassword.indexOf(PASSWORD_DELIMITER);
        if (delimiterIndex >= 0) {
            salt = storedPassword.substring(0, delimiterIndex);
            hash = storedPassword.substring(delimiterIndex + 1);
        }

        return new UserAccount(
                rs.getLong("id"),
                rs.getString("name"),
                rs.getString("user_id"),
                rs.getString("email"),
                hash,
                salt);
    }
}
