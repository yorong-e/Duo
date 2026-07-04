(function () {
  "use strict";

  const signupForm = document.getElementById("signup-form");
  const loginForm = document.getElementById("login-form");
  const duplicateChecks = {
    username: { value: "", available: false },
    email: { value: "", available: false },
  };

  if (signupForm) initSignup(signupForm);
  if (loginForm) initLogin(loginForm);

  function initSignup(form) {
    form.querySelectorAll("[data-check]").forEach((button) => {
      button.addEventListener("click", () => checkDuplicate(form, button.dataset.check));
    });

    ["username", "email"].forEach((name) => {
      form.elements[name].addEventListener("input", () => {
        duplicateChecks[name] = { value: "", available: false };
      });
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      clearErrors(form);

      const payload = getFormPayload(form);
      const errors = validateSignup(payload);

      if (!duplicateChecks.username.available || duplicateChecks.username.value !== payload.username) {
        errors.username = errors.username || "아이디 중복 확인을 완료해주세요.";
      }
      if (!duplicateChecks.email.available || duplicateChecks.email.value !== payload.email) {
        errors.email = errors.email || "이메일 중복 확인을 완료해주세요.";
      }

      if (showErrors(form, errors)) return;

      postJson("/api/auth/signup", payload)
        .then(() => {
          setMessage("signup-message", "회원가입이 완료되었습니다. 로그인 페이지로 이동합니다.", "success");
          window.setTimeout(() => {
            window.location.href = "/login.html";
          }, 700);
        })
        .catch((error) => showServerError(form, "signup-message", error));
    });
  }

  function initLogin(form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      clearErrors(form);

      const payload = getFormPayload(form);
      const errors = validateLogin(payload);
      if (showErrors(form, errors)) return;

      postJson("/api/auth/login", payload)
        .then(() => {
          setMessage("login-message", "로그인되었습니다. 메인 페이지로 이동합니다.", "success");
          window.setTimeout(() => {
            window.location.href = "/";
          }, 400);
        })
        .catch((error) => showServerError(form, "login-message", error));
    });
  }

  function checkDuplicate(form, type) {
    clearFieldError(form, type);
    const value = form.elements[type].value.trim();
    const errors = type === "email"
      ? validateEmailField(value)
      : validateUsernameField(value);

    if (errors) {
      setFieldError(form, type, errors);
      duplicateChecks[type] = { value: "", available: false };
      return;
    }

    fetch(`/api/auth/check-${type}?${type}=${encodeURIComponent(value)}`)
      .then((response) => response.ok ? response.json() : Promise.reject(response))
      .then((result) => {
        duplicateChecks[type] = { value, available: result.available };
        setFieldError(form, type, result.available ? "사용 가능합니다." : "이미 사용 중입니다.", result.available);
      })
      .catch(() => {
        duplicateChecks[type] = { value: "", available: false };
        setFieldError(form, type, "중복 확인 중 오류가 발생했습니다.");
      });
  }

  function getFormPayload(form) {
    return Array.from(new FormData(form).entries()).reduce((payload, entry) => {
      payload[entry[0]] = typeof entry[1] === "string" ? entry[1].trim() : entry[1];
      return payload;
    }, Array.from(form.elements).reduce((payload, element) => {
      if (element.type === "checkbox" && element.name) {
        payload[element.name] = element.checked;
      }
      return payload;
    }, {}));
  }

  function validateSignup(payload) {
    const errors = {};
    if (!payload.name) errors.name = "이름을 입력해주세요.";
    const usernameError = validateUsernameField(payload.username);
    if (usernameError) errors.username = usernameError;
    const emailError = validateEmailField(payload.email);
    if (emailError) errors.email = emailError;
    const passwordError = validatePasswordField(payload.password);
    if (passwordError) errors.password = passwordError;
    if (!payload.confirmPassword) {
      errors.confirmPassword = "비밀번호 확인을 입력해주세요.";
    } else if (payload.password !== payload.confirmPassword) {
      errors.confirmPassword = "비밀번호가 일치하지 않습니다.";
    }
    return errors;
  }

  function validateLogin(payload) {
    const errors = {};
    if (!payload.username) errors.username = "아이디를 입력해주세요.";
    if (!payload.password) errors.password = "비밀번호를 입력해주세요.";
    return errors;
  }

  function validateUsernameField(value) {
    if (!value) return "아이디를 입력해주세요.";
    if (!/^[A-Za-z0-9_]{4,20}$/.test(value)) return "아이디는 영문, 숫자, 밑줄 4~20자로 입력해주세요.";
    return "";
  }

  function validateEmailField(value) {
    if (!value) return "이메일을 입력해주세요.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return "올바른 이메일 형식으로 입력해주세요.";
    return "";
  }

  function validatePasswordField(value) {
    if (!value) return "비밀번호를 입력해주세요.";
    if (value.length < 8) return "비밀번호는 8자 이상이어야 합니다.";
    if (!/[A-Za-z]/.test(value) || !/[0-9]/.test(value)) return "비밀번호는 영문과 숫자를 포함해야 합니다.";
    return "";
  }

  function postJson(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((response) => {
      if (response.ok) return response.json();
      return response.json()
        .catch(() => ({ message: "요청을 처리할 수 없습니다." }))
        .then((body) => Promise.reject(body));
    });
  }

  function clearErrors(form) {
    form.querySelectorAll(".field-error").forEach((node) => {
      node.textContent = "";
      node.classList.remove("success");
    });
    form.querySelectorAll(".field-group").forEach((node) => node.classList.remove("has-error"));
    form.querySelectorAll(".form-message").forEach((node) => {
      node.textContent = "";
      node.classList.remove("success", "error");
    });
  }

  function clearFieldError(form, field) {
    const target = form.querySelector(`[data-error-for="${field}"]`);
    const group = target ? target.closest(".field-group") : null;
    if (target) {
      target.textContent = "";
      target.classList.remove("success");
    }
    if (group) group.classList.remove("has-error");
  }

  function showErrors(form, errors) {
    Object.entries(errors).forEach(([field, message]) => setFieldError(form, field, message));
    return Object.keys(errors).length > 0;
  }

  function setFieldError(form, field, message, success) {
    const target = form.querySelector(`[data-error-for="${field}"]`);
    const group = target ? target.closest(".field-group") : null;
    if (!target) return;
    target.textContent = message;
    target.classList.toggle("success", Boolean(success));
    if (group) group.classList.toggle("has-error", !success);
  }

  function setMessage(id, message, type) {
    const target = document.getElementById(id);
    if (!target) return;
    target.textContent = message;
    target.classList.remove("success", "error");
    target.classList.add(type);
  }

  function showServerError(form, messageId, error) {
    if (error && error.field) {
      setFieldError(form, error.field, error.message || "입력값을 확인해주세요.");
    }
    setMessage(messageId, error && error.message ? error.message : "요청을 처리할 수 없습니다.", "error");
  }
})();
