package com.duo.app.config;

import jakarta.servlet.MultipartConfigElement;
import org.springframework.boot.web.servlet.MultipartConfigFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.util.unit.DataSize;

@Configuration
public class UploadConfig {

    private static final DataSize FLOORPLAN_UPLOAD_LIMIT = DataSize.ofMegabytes(512);

    @Bean
    public MultipartConfigElement multipartConfigElement() {
        MultipartConfigFactory factory = new MultipartConfigFactory();
        factory.setMaxFileSize(FLOORPLAN_UPLOAD_LIMIT);
        factory.setMaxRequestSize(FLOORPLAN_UPLOAD_LIMIT);
        return factory.createMultipartConfig();
    }
}
