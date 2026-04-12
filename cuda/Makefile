# TSAR BOMBA CUDA Makefile
# =====================
# Compile CUDA kernels for T4/NVIDIA GPUs

CUDA_ARCH = 75  # T4 (sm_75)
NVCC = nvcc
CFLAGS = -O3 --use_fast_math -maxrregcount=32
LDFLAGS = -lcuda -lcudart

# Target GPU (default T4)
TARGET ?= t4

# Architecture flags
ifeq ($(TARGET),t4)
    CUDA_ARCH = 75
    N_WALKERS = 20480
else ifeq ($(TARGET),v100)
    CUDA_ARCH = 70
    N_WALKERS = 25600
else ifeq ($(TARGET),a100)
    CUDA_ARCH = 80
    N_WALKERS = 40960
else
    $(error Unknown target: $(TARGET))
endif

# Sources
SOURCES = kangaroo_walk_cuda.cu point_add_cuda.cu
OBJECTS = $(SOURCES:.cu=.o)

# Output
OUTPUT = libtsar_bomba_gpu.a

.PHONY: all clean test

all: $(OUTPUT)

$(OUTPUT): $(OBJECTS)
	ar rcs $@ $^

%.o: %.cu
	$(NVCC) $(CFLAGS) -arch=sm_$(CUDA_ARCH) -c $< -o $@

clean:
	rm -f $(OBJECTS) $(OUTPUT)

test: $(OUTPUT)
	@echo "=== TSAR BOMBA CUDA Test ==="
	@echo "Target: $(TARGET) (sm_$(CUDA_ARCH))"
	@echo "Walkers: $(N_WALKERS)"
	@nvidia-smi --query-gpu=name,memory.free,memory.total --format=csv

install: $(OUTPUT)
	mkdir -p ../lib
	cp $(OUTPUT) ../lib/
	@echo "Installed to ../lib/$(OUTPUT)"