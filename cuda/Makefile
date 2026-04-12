# TSAR BOMBA CUDA Build
TARGET = t4
NVCC = nvcc

NVCC_FLAGS = -O3 -use_fast_math -maxrregcount=64 -lineinfo -diag-suppress=177
CUDA_ARCH = 75

OUTPUT = libtsar_bomba_gpu.a

all: $(OUTPUT)

$(OUTPUT): kangaroo_walk_cuda.o
	ar rcs $@ $<

kangaroo_walk_cuda.o: kangaroo_walk_cuda.cu
	$(NVCC) $(NVCC_FLAGS) -arch=sm_$(CUDA_ARCH) -c $< -o $@

clean:
	rm -f *.o $(OUTPUT)
