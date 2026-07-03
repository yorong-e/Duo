# DuO Core Engine — shared library build
# Usage:
#   make          # build for current OS
#   make clean    # remove artifacts

CXX      := g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -fPIC
TARGET   := libduo_engine

UNAME_S := $(shell uname -s 2>/dev/null || echo Unknown)

ifeq ($(UNAME_S),Darwin)
  LIB_EXT := dylib
  LDFLAGS := -dynamiclib
else ifeq ($(OS),Windows_NT)
  LIB_EXT := dll
  LDFLAGS := -shared
else
  LIB_EXT := so
  LDFLAGS := -shared
endif

OUTPUT := $(TARGET).$(LIB_EXT)

.PHONY: all clean

all: $(OUTPUT)

$(OUTPUT): engine.cpp
	$(CXX) $(CXXFLAGS) $(LDFLAGS) -o $@ $<

clean:
	rm -f $(TARGET).so $(TARGET).dylib $(TARGET).dll *.o
