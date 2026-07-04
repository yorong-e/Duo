package com.duo.app.model;

public record UserAccount(
        long id,
        String name,
        String username,
        String email,
        String passwordHash,
        String passwordSalt) {
}
