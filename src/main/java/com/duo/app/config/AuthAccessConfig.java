package com.duo.app.config;

import com.duo.app.controller.AuthController;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import java.io.IOException;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class AuthAccessConfig implements WebMvcConfigurer {

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new LoginRequiredInterceptor())
                .addPathPatterns("/", "/index.html", "/api/furniture/**");
    }

    private static class LoginRequiredInterceptor implements HandlerInterceptor {

        @Override
        public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
                throws IOException {
            if (isAuthenticated(request)) {
                return true;
            }

            if (request.getRequestURI().startsWith("/api/")) {
                response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                response.setContentType("application/json;charset=UTF-8");
                response.getWriter().write("{\"message\":\"로그인이 필요합니다.\"}");
                return false;
            }

            response.sendRedirect("/login.html");
            return false;
        }

        private boolean isAuthenticated(HttpServletRequest request) {
            HttpSession session = request.getSession(false);
            return session != null && session.getAttribute(AuthController.SESSION_USERNAME) instanceof String;
        }
    }
}
