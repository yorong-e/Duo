package com.duo.app.config;

import java.nio.file.Path;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class FloorImageResourceConfig implements WebMvcConfigurer {

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        String camelCaseLocation = directoryLocation("floorImage");
        String lowercaseLocation = directoryLocation("floorimage");
        registry.addResourceHandler("/floorimage/**")
                .addResourceLocations(camelCaseLocation, lowercaseLocation);
    }

    private String directoryLocation(String name) {
        String uri = Path.of("src", name).toAbsolutePath().normalize().toUri().toString();
        return uri.endsWith("/") ? uri : uri + "/";
    }
}
