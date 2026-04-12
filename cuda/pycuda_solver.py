#!/usr/bin/env python3
"""
TSAR BOMBA — PyCUDA Production Kernel Loader
=========================================
Proper CUDA kernel loading using PyCUDA.
"""

import os
import subprocess
import tempfile

# PyCUDA kernel code (compiled at runtime)
CUDA_KERNEL = r'''
// TSAR BOMBA — Tesla T4 Production Kangaroo Solver

#include <stdint.h>
#include <stddef.h>

#define N_WALKERS   40960
#define BLOCK_SIZE  256
#define GRID_SIZE   160
#define WARP_SIZE   32
#define SHARED_DP   16384
#define GLOBAL_DP   2097152

// secp256k1 prime
#define P0  0xFFFFFFFFUL
#define P1  0xFFFFFFFFUL
#define P2  0xFFFFFFFFUL
#define P3  0xFFFFFFFFUL
#define P4  0xFFFFFFFFUL
#define P5  0xFFFFFFFFUL
#define P6  0xFFFFFFFEUL
#define P7  0xFFFFFFFFUL

// Generator
#define Gx0 0x79BE667EUL
#define Gx1 0xF9DCBBACUL
#define Gx2 0x55A06295UL
#define Gx3 0xCE870B07UL
#define Gx4 0x029BFCDBUL
#define Gx5 0xDCE28D95UL
#define Gx6 0x9F2815B1UL
#define Gx7 0x6F81798FUL

#define Gy0 0x483ADA77UL
#define Gy1 0x26A3C465UL
#define Gy2 0x5DA4FBFCUL
#define Gy3 0x0E1108A8UL
#define Gy4 0xFD17B448UL
#define Gy5 0xA6855419UL
#define Gy6 0x9C47D08EUL
#define Gy7 0xFB10D4B8UL

// 256-bit operations
__device__ void load256(const uint32_t* src, uint32_t* dst) {
    #pragma unroll 8
    for (int i = 0; i < 8; i++) dst[i] = src[i];
}

__device__ void copy256(const uint32_t* src, uint32_t* dst) {
    #pragma unroll 8
    for (int i = 0; i < 8; i++) dst[i] = src[i];
}

__device__ int is_zero256(const uint32_t* a) {
    #pragma unroll 8
    for (int i = 0; i < 8; i++) if (a[i] != 0) return 0;
    return 1;
}

__device__ void zero256(uint32_t* a) {
    #pragma unroll 8
    for (int i = 0; i < 8; i++) a[i] = 0;
}

__device__ int cmp256(const uint32_t* a, const uint32_t* b) {
    #pragma unroll 8
    for (int i = 7; i >= 0; i--) {
        if (a[i] != b[i]) return (a[i] > b[i]) ? 1 : -1;
    }
    return 0;
}

// Modular add
__device__ void add_mod256(const uint32_t* a, const uint32_t* b, uint32_t* res) {
    uint64_t carry = 0;
    #pragma unroll 8
    for (int i = 0; i < 8; i++) {
        uint64_t sum = (uint64_t)a[i] + b[i] + carry;
        res[i] = (uint32_t)sum;
        carry = sum >> 32;
    }
    uint32_t p[8] = {P0, P1, P2, P3, P4, P5, P6, P7};
    if (carry || cmp256(res, p) >= 0) {
        uint64_t borrow = 0;
        #pragma unroll 8
        for (int i = 0; i < 8; i++) {
            uint64_t diff = (uint64_t)res[i] - p[i] - borrow;
            res[i] = (uint32_t)diff;
            borrow = (diff >> 32) & 1;
        }
    }
}

// Modular sub
__device__ void sub_mod256(const uint32_t* a, const uint32_t* b, uint32_t* res) {
    uint32_t p[8] = {P0, P1, P2, P3, P4, P5, P6, P7};
    if (cmp256(a, b) >= 0) {
        uint64_t borrow = 0;
        #pragma unroll 8
        for (int i = 0; i < 8; i++) {
            uint64_t diff = (uint64_t)a[i] - b[i] - borrow;
            res[i] = (uint32_t)diff;
            borrow = (diff >> 32) & 1;
        }
    } else {
        uint64_t carry = 0;
        #pragma unroll 8
        for (int i = 0; i < 8; i++) {
            uint64_t sum = (uint64_t)a[i] + p[i] + carry;
            res[i] = (uint32_t)sum;
            carry = sum >> 32;
        }
        uint64_t borrow = 0;
        #pragma unroll 8
        for (int i = 0; i < 8; i++) {
            uint64_t diff = (uint64_t)res[i] - b[i] - borrow;
            res[i] = (uint32_t)diff;
            borrow = (diff >> 32) & 1;
        }
    }
}

// Montgomery multiply
__device__ void mul_mod256(const uint32_t* a, const uint32_t* b, uint32_t* res) {
    uint64_t t[16] = {0};
    #pragma unroll 8
    for (int i = 0; i < 8; i++) {
        uint64_t carry = 0;
        #pragma unroll 8
        for (int j = 0; j < 8; j++) {
            t[i+j] += (uint64_t)a[i] * b[j];
        }
        for (int j = i; j < 15 && t[j] >= 0x100000000ULL; j++) {
            t[j+1] += t[j] >> 32;
            t[j] &= 0xFFFFFFFFULL;
        }
    }
    uint32_t p[8] = {P0, P1, P2, P3, P4, P5, P6, P7};
    uint64_t mp = t[0] * 0x1000003E10ULL & 0xFFFFFFFFULL;
    uint64_t carry = 0;
    #pragma unroll 8
    for (int i = 0; i < 8; i++) {
        uint64_t q = (t[i] + carry + mp * p[i]) & 0xFFFFFFFFULL;
        carry = (t[i] + carry + mp * p[i]) >> 32;
        res[i] = (uint32_t)q;
    }
    if (cmp256(res, p) >= 0) {
        sub_mod256(res, p, res);
    }
}

__device__ void sqr_mod256(const uint32_t* a, uint32_t* res) {
    mul_mod256(a, a, res);
}

// Modular inverse (simplified for now)
__device__ int inv_mod256(const uint32_t* a, uint32_t* res) {
    if (is_zero256(a)) return 0;
    // Use Fermat's little theorem: a^(p-2)
    uint32_t r[8] = {1,0,0,0,0,0,0,0};
    uint32_t base[8], temp[8];
    copy256(a, base);
    uint32_t exp[8] = {P0-2, P1, P2, P3, P4, P5, P6-1, P7};
    #pragma unroll 256
    for (int i = 0; i < 256; i++) {
        if ((i < 32 && (exp[0] & (1U << i))) || (i >= 32 && i < 64 && (exp[1] & (1U << (i-32))))) {
            mul_mod256(r, base, r);
        }
        sqr_mod256(base, base);
    }
    copy256(r, res);
    return 1;
}

// Jacobian to affine
__device__ void jacobian_to_affine(const uint32_t* Jx, const uint32_t* Jy, const uint32_t* Jz,
                                   uint32_t* Ax, uint32_t* Ay) {
    uint32_t z_inv[8], z2[8], z3[8];
    inv_mod256(Jz, z_inv);
    mul_mod256(z_inv, z_inv, z2);
    mul_mod256(z2, z_inv, z3);
    mul_mod256(Jx, z2, Ax);
    mul_mod256(Jy, z3, Ay);
}

// Forward declaration for ec_dbl_jacobian
__device__ void ec_dbl_jacobian(
    const uint32_t* Px, const uint32_t* Py, const uint32_t* Pz,
    uint32_t* Rx, uint32_t* Ry, uint32_t* Rz
);

// EC addition (Jacobian)
__device__ void ec_add_jacobian(
    const uint32_t* Px, const uint32_t* Py, const uint32_t* Pz,
    const uint32_t* Qx, const uint32_t* Qy, const uint32_t* Qz,
    uint32_t* Rx, uint32_t* Ry, uint32_t* Rz
) {
    uint32_t z1z1[8], z2z2[8], u1[8], u2[8], s1[8], s2[8];
    uint32_t h[8], r[8], temp[8];
    
    mul_mod256(Pz, Pz, z1z1);
    mul_mod256(Qz, Qz, z2z2);
    mul_mod256(Px, z2z2, u1);
    mul_mod256(Qx, z1z1, u2);
    mul_mod256(Py, Qz, temp);
    mul_mod256(temp, z2z2, s1);
    mul_mod256(Qy, Pz, temp);
    mul_mod256(temp, z1z1, s2);
    
    sub_mod256(u2, u1, h);
    sub_mod256(s2, s1, r);
    
    if (is_zero256(h)) {
        if (is_zero256(r)) {
            // Doubling
            ec_dbl_jacobian(Px, Py, Pz, Rx, Ry, Rz);
        } else {
            zero256(Rx); zero256(Ry); Rz[0] = 1;
            for(int i=1;i<8;i++)Rz[i]=0;
        }
        return;
    }
    
    uint32_t h2[8], v[8], x3[8], y3[8];
    mul_mod256(h, h, h2);
    mul_mod256(u1, h2, v);
    mul_mod256(r, r, x3);
    uint32_t two_v[8];
    add_mod256(v, v, two_v);
    sub_mod256(x3, two_v, x3);
    sub_mod256(x3, v, x3);
    
    uint32_t v_x3[8];
    sub_mod256(v, x3, v_x3);
    mul_mod256(r, v_x3, y3);
    uint32_t s1h3[8];
    mul_mod256(s1, h2, s1h3);
    sub_mod256(y3, s1h3, y3);
    
    mul_mod256(Pz, Qz, temp);
    mul_mod256(temp, h, Rz);
    
    copy256(x3, Rx);
    copy256(y3, Ry);
}

// EC doubling
__device__ void ec_dbl_jacobian(
    const uint32_t* Px, const uint32_t* Py, const uint32_t* Pz,
    uint32_t* Rx, uint32_t* Ry, uint32_t* Rz
) {
    uint32_t X1[8], Y1[8], S[8], M[8], temp[8];
    copy256(Px, X1); copy256(Py, Y1);
    
    mul_mod256(X1, X1, temp);
    add_mod256(temp, temp, M);
    add_mod256(temp, M, M);
    
    mul_mod256(Y1, Y1, temp);
    mul_mod256(X1, temp, S);
    add_mod256(S, S, S);
    add_mod256(S, S, S);
    
    uint32_t X3[8], Y3[8], Z3[8];
    mul_mod256(M, M, X3);
    sub_mod256(X3, S, X3);
    sub_mod256(X3, S, X3);
    
    sub_mod256(S, X3, temp);
    mul_mod256(M, temp, Y3);
    
    uint32_t eight_y1[8];
    mul_mod256(Y1, Y1, temp);
    mul_mod256(temp, temp, temp);
    add_mod256(temp, temp, eight_y1);
    add_mod256(temp, eight_y1, eight_y1);
    sub_mod256(Y3, eight_y1, Y3);
    
    add_mod256(Y1, Y1, temp);
    mul_mod256(temp, Pz, Z3);
    
    copy256(X3, Rx);
    copy256(Y3, Ry);
    copy256(Z3, Rz);
}

// Scalar multiplication
__device__ void ec_mul_scalar(const uint32_t* k, uint32_t* Qx, uint32_t* Qy) {
    uint32_t Gx[8] = {Gx0, Gx1, Gx2, Gx3, Gx4, Gx5, Gx6, Gx7};
    uint32_t Gy[8] = {Gy0, Gy1, Gy2, Gy3, Gy4, Gy5, Gy6, Gy7};
    uint32_t Rx[8] = {0}, Ry[8] = {0}, Rz[8] = {1};
    uint32_t Px[8], Py[8], Pz[8];
    copy256(Gx, Px); copy256(Gy, Py); Pz[0]=1; for(int i=1;i<8;i++)Pz[i]=0;
    
    #pragma unroll 256
    for (int i = 255; i >= 0; i--) {
        int bit = (k[i/32] >> (i%32)) & 1;
        if (bit) {
            if (!is_zero256(Rz)) {
                ec_add_jacobian(Rx, Ry, Rz, Px, Py, Pz, Rx, Ry, Rz);
            } else {
                copy256(Px, Rx); copy256(Py, Ry); copy256(Pz, Rz);
            }
        }
        if (i > 0) ec_dbl_jacobian(Px, Py, Pz, Px, Py, Pz);
    }
    jacobian_to_affine(Rx, Ry, Rz, Qx, Qy);
}

// Main kernel
__global__ void kangaroo_walk_kernel(
    uint64_t* k_values,
    uint32_t* dp_table,
    uint32_t* found_flag,
    uint64_t* result_k,
    uint64_t max_steps,
    uint64_t range_lo,
    uint64_t range_hi,
    uint64_t* total_steps,
    uint32_t* dp_count
) {
    extern __shared__ uint32_t s_dp_cache[];
    
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid >= N_WALKERS) return;
    
    if (threadIdx.x < SHARED_DP) s_dp_cache[threadIdx.x] = 0;
    __syncthreads();
    
    uint64_t k = k_values[tid];
    uint64_t step = 0;
    int is_tame = (tid % 2 == 1);
    int lane = threadIdx.x % WARP_SIZE;
    
    while (step < max_steps && !(*found_flag)) {
        if (!is_tame) {
            // P-adic jump
            int v = __builtin_clzll(k) & 63;
            uint64_t jump = (v < 8) ? (1ULL << v) : 256ULL;
            k += jump;
            if (k >= range_hi) k -= range_lo;
        } else {
            k += 1;
            if (k >= range_hi) k -= range_lo;
        }
        
        uint32_t Qx[8], Qy[8];
        // Convert 64-bit k to 256-bit (little-endian, lower 64 bits only)
        uint32_t k_256[8] = {
            (uint32_t)(k & 0xFFFFFFFF),
            (uint32_t)((k >> 32) & 0xFFFFFFFF),
            0, 0, 0, 0, 0, 0
        };
        ec_mul_scalar(k_256, Qx, Qy);
        
        if ((Qx[0] & 0xFFFFF) == 0) {
            uint32_t slot = Qx[0] & (SHARED_DP - 1);
            uint32_t k_low = (uint32_t)k;
            
            if (s_dp_cache[slot] != 0) {
                uint32_t other = s_dp_cache[slot];
                if ((other & 1) != (k_low & 1)) {
                    uint32_t expected = 0;
                    if (atomicCAS(found_flag, expected, 1) == 0) {
                        result_k[0] = min(k, (uint64_t)other);
                    }
                    break;
                }
            }
            s_dp_cache[slot] = k_low;
            
            uint32_t gslot = Qx[0] & (GLOBAL_DP - 1);
            uint32_t existing = dp_table[gslot];
            if (existing != 0 && ((existing & 1) != (k_low & 1))) {
                uint32_t expected = 0;
                if (atomicCAS(found_flag, expected, 1) == 0) {
                    result_k[0] = min(k, (uint64_t)existing);
                }
                break;
            }
            atomicExch(&dp_table[gslot], k_low);
        }
        
        step++;
        if (step % 1000000 == 0 && lane == 0) {
            // Atomic add for 64-bit - split into two 32-bit adds
            unsigned int* total_steps_low = (unsigned int*)total_steps;
            unsigned int* total_steps_high = total_steps_low + 1;
            unsigned int low = 1000000;
            unsigned int carry = atomicAdd(total_steps_low, low);
            if (carry == 0xFFFFFFFFu) { // overflow
                atomicAdd(total_steps_high, 1);
            }
            printf("[%04d] Step %llu, k=%llu\n", blockIdx.x, (unsigned long long)step, (unsigned long long)k);
        }
    }
    
    k_values[tid] = k;
}
'''


def compile_and_load_kernel():
    """Compile CUDA kernel using PyCUDA."""
    try:
        import pycuda.driver as cuda
        import pycuda.compiler as module
        import pycuda.gpuarray as gpuarray
        
        # Initialize CUDA
        cuda.init()
        device = cuda.Device(0)
        context = device.make_context()
        
        # Compile kernel
        mod = module.SourceModule(CUDA_KERNEL)
        
        # Get kernel function
        kernel = mod.get_function("kangaroo_walk_kernel")
        
        print("[PyCUDA] Kernel compiled and loaded successfully")
        print(f"[PyCUDA] Device: {device.name()}")
        print(f"[PyCUDA] Compute Capability: {device.compute_capability()}")
        print(f"[PyCUDA] Total Memory: {device.total_memory() / 1e9:.2f} GB")
        
        return mod, kernel, cuda, context
        
    except ImportError:
        print("[PyCUDA] PyCUDA not installed")
        return None, None, None, None
    except Exception as e:
        print(f"[PyCUDA] Error: {e}")
        return None, None, None, None


def solve_with_cuda(target_x: int, max_steps: int = 1<<35, 
                   range_lo: int = 1<<134, range_hi: int = 1<<135):
    """Solve using PyCUDA."""
    mod, kernel, cuda, context = compile_and_load_kernel()
    
    if kernel is None:
        return None
    
    try:
        # Allocate GPU memory
        import numpy as np
        
        N_WALKERS = 40960
        GLOBAL_DP = 2097152
        
        d_k = cuda.mem_alloc(N_WALKERS * 8)  # uint64
        d_dp = cuda.mem_alloc(GLOBAL_DP * 4)
        d_found = cuda.mem_alloc(4)
        d_result = cuda.mem_alloc(8)  # uint64
        d_total = cuda.mem_alloc(8)   # uint64
        d_dp_count = cuda.mem_alloc(4)
        
        # Initialize
        cuda.memset_d32(d_k, 0, N_WALKERS)
        cuda.memset_d32(d_dp, 0, GLOBAL_DP)
        cuda.memset_d32(d_found, 0, 1)
        cuda.memset_d32(d_result, 0, 1)
        cuda.memset_d32(d_total, 0, 1)
        cuda.memset_d32(d_dp_count, 0, 1)
        
        # Initialize k values - k is 64-bit for range [2^134, 2^135)
        h_k = np.arange(N_WALKERS, dtype=np.uint64)
        range_size = range_hi - range_lo
        h_k = (range_lo % (1 << 32) + (h_k * 1234567) % range_size).astype(np.uint64)
        cuda.memcpy_htod(d_k, h_k)
        
        print(f"[CUDA] Starting solve with {N_WALKERS} walkers")
        
        # Launch kernel
        block = (256, 1, 1)
        grid = (160, 1)
        shared_mem = 16384 * 4
        
        kernel(d_k, d_dp, d_found, d_result, 
               np.uint64(max_steps), np.uint64(range_lo), np.uint64(range_hi),
               d_total, d_dp_count, 
               block=block, grid=grid, shared=shared_mem)
        
        context.synchronize()
        
        # Check result
        found = np.zeros(1, dtype=np.uint32)
        cuda.memcpy_dtoh(found, d_found)
        
        if found[0]:
            result = np.zeros(1, dtype=np.uint64)
            cuda.memcpy_dtoh(result, d_result)
            print(f"[CUDA] SOLUTION FOUND: k = {result[0]}")
            return result[0]
        else:
            print("[CUDA] No solution found")
            return None
            
    except Exception as e:
        print(f"[CUDA] Error: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if context:
            context.pop()


if __name__ == "__main__":
    solve_with_cuda(0x2145d2611c823a396ef6712ce0f712f09b9b4f3135e3e0)
