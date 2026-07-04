package com.duo.app.service;

public class AuthValidationException extends RuntimeException {

    private final String field;

    public AuthValidationException(String field, String message) {
        super(message);
        this.field = field;
    }

    public String getField() {
        return field;
    }
}
