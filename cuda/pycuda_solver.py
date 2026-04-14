#!/usr/bin/env python3
"""PyCUDA solver for Tesla T4 - With progress monitoring."""
import sys
sys.path.insert(0, '/teamspace/studios/this_studio')

import pycuda.driver as cuda
import pycuda.compiler as compiler
import pycuda.gpuarray as gpuarray
import numpy as np
import time
import threading

# ═══════════════════════════════════════════════════════════════════════════════
# FIXED CUDA KERNEL — With progress reporting
# ═══════════════════════════════════════════════════════════════════════════════

CUDA_KERNEL = r'''
#include <stdint.h>
#include <stdio.h>

#define N_WALKERS_PER_BLOCK 256
#define N_BLOCKS 160
#define TOTAL_WALKERS (N_BLOCKS * N_WALKERS_PER_BLOCK)

// secp256k1 prime P = 2^256 - 2^32 - 977
__constant__ uint32_t P_LIMBS[8] = {
    0xFFFFFC2F, 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFF,
    0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF
};

// Generator point G
__constant__ uint32_t GX_LIMBS[8] = {
    0x16F81798, 0x59F2815B, 0x2DCE28D9, 0x029BFCDB,
    0xCE870B07, 0x55A06295, 0xF9DCBBAC, 0x79BE667E
};
__constant__ uint32_t GY_LIMBS[8] = {
    0xFB10D4B8, 0x9C47D08F, 0xA6855419, 0xFD17B448,
    0x0E1108A8, 0x5DA4FBFC, 0x26A3C465, 0x483ADA77
};

// Curve order N
__constant__ uint32_t N_LIMBS[8] = {
    0xD0364141, 0xBFD25E8C, 0xAF48A03B, 0xBAAEDCE6,
    0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF
};

// Puzzle 135 target
__constant__ uint32_t TARGET_X[8] = {
    0xD08D1E16, 0x230FB9B6, 0x3E3E0AA3, 0x9B4F3135,
    0x0F712F09, 0xEF6712CE, 0xC823A396, 0x145D2611
};
__constant__ uint32_t TARGET_Y[8] = {
    0xF23A8FF, 0x7595EF62, 0x8FFE4DF3, 0xD3F06343,
    0xA742ED31, 0xFEBD499A, 0x5E422908, 0x9985FA16
};

#define N_JUMPS 32
#define JUMP_BASE_BIT 52
#define DP_BITS 20
#define DP_MASK ((1u << DP_BITS) - 1u)
#define PROGRESS_INTERVAL 100000  // Report every 100k steps

typedef struct {
    uint32_t x[8];
    uint32_t y[8];
    uint32_t k[8];
    uint64_t steps;
    uint32_t ktype;
    uint32_t dp_count;
    uint32_t pad[5];
} WalkerState;

typedef struct {
    uint32_t x[8];
    uint32_t y[8];
} JumpPoint;

// Progress counter (global)
__device__ volatile uint64_t g_progress_counter = 0;
__device__ volatile uint32_t g_last_report = 0;

__device__ void add_mod_p(const uint32_t* a, const uint32_t* b, uint32_t* r) {
    uint64_t carry = 0;
    #pragma unroll
    for (int i = 0; i < 8; i++) {
        carry += (uint64_t)a[i] + b[i];
        r[i] = (uint32_t)carry;
        carry >>= 32;
    }
    if (carry) {
        uint64_t borrow = 0;
        #pragma unroll
        for (int i = 0; i < 8; i++) {
            borrow = (uint64_t)r[i] - P_LIMBS[i] - borrow;
            r[i] = (uint32_t)borrow;
            borrow = (borrow >> 63) & 1;
        }
    }
}

__device__ void sub_mod_p(const uint32_t* a, const uint32_t* b, uint32_t* r) {
    uint64_t borrow = 0;
    #pragma unroll
    for (int i = 0; i < 8; i++) {
        borrow = (uint64_t)a[i] - b[i] - borrow;
        r[i] = (uint32_t)borrow;
        borrow = (borrow >> 63) & 1;
    }
    if (borrow) {
        uint64_t carry = 0;
        #pragma unroll
        for (int i = 0; i < 8; i++) {
            carry += (uint64_t)r[i] + P_LIMBS[i];
            r[i] = (uint32_t)carry;
            carry >>= 32;
        }
    }
}

__device__ void add_mod_n(const uint32_t* a, const uint32_t* b, uint32_t* r) {
    uint64_t carry = 0;
    #pragma unroll
    for (int i = 0; i < 8; i++) {
        carry += (uint64_t)a[i] + b[i];
        r[i] = (uint32_t)carry;
        carry >>= 32;
    }
    int cmp = 0;
    for (int i = 7; i >= 0; i--) {
        if (r[i] > N_LIMBS[i]) { cmp = 1; break; }
        if (r[i] < N_LIMBS[i]) { cmp = -1; break; }
    }
    if (carry || cmp >= 0) {
        uint64_t borrow = 0;
        #pragma unroll
        for (int i = 0; i < 8; i++) {
            borrow = (uint64_t)r[i] - N_LIMBS[i] - borrow;
            r[i] = (uint32_t)borrow;
            borrow = (borrow >> 63) & 1;
        }
    }
}

__device__ void sub_mod_n(const uint32_t* a, const uint32_t* b, uint32_t* r) {
    uint64_t borrow = 0;
    #pragma unroll
    for (int i = 0; i < 8; i++) {
        borrow = (uint64_t)a[i] - b[i] - borrow;
        r[i] = (uint32_t)borrow;
        borrow = (borrow >> 63) & 1;
    }
    if (borrow) {
        uint64_t carry = 0;
        #pragma unroll
        for (int i = 0; i < 8; i++) {
            carry += (uint64_t)r[i] + N_LIMBS[i];
            r[i] = (uint32_t)carry;
            carry >>= 32;
        }
    }
}

__device__ int is_zero(const uint32_t* a) {
    uint32_t acc = 0;
    #pragma unroll
    for (int i = 0; i < 8; i++) acc |= a[i];
    return acc == 0;
}

__device__ int u256_eq(const uint32_t* a, const uint32_t* b) {
    uint32_t acc = 0;
    #pragma unroll
    for (int i = 0; i < 8; i++) acc |= (a[i] ^ b[i]);
    return acc == 0;
}

__device__ void set_bit(uint32_t* a, int bit) {
    a[bit >> 5] |= (1u << (bit & 31));
}

__device__ void mul_mod_p(const uint32_t* a, const uint32_t* b, uint32_t* r) {
    uint64_t acc[16] = {0};
    #pragma unroll
    for (int i = 0; i < 8; i++) {
        #pragma unroll
        for (int j = 0; j < 8; j++) {
            acc[i+j] += (uint64_t)a[i] * b[j];
        }
    }
    uint64_t carry = 0;
    #pragma unroll
    for (int i = 0; i < 16; i++) {
        acc[i] += carry;
        carry = acc[i] >> 32;
        acc[i] &= 0xFFFFFFFF;
    }
    for (int i = 0; i < 8; i++) r[i] = (uint32_t)acc[i];
    uint64_t high[8] = {0};
    for (int i = 0; i < 8; i++) high[i] = acc[i+8];
    uint64_t term1[8] = {0};
    for (int i = 0; i < 8; i++) term1[i] = high[i] << 32;
    uint64_t term2[8] = {0};
    for (int i = 0; i < 8; i++) term2[i] = high[i] * 977;
    carry = 0;
    #pragma unroll
    for (int i = 0; i < 8; i++) {
        carry += (uint64_t)r[i] + term1[i] + term2[i];
        r[i] = (uint32_t)carry;
        carry >>= 32;
    }
    if (carry) {
        uint64_t borrow = 0;
        uint32_t tmp[8];
        #pragma unroll
        for (int i = 0; i < 8; i++) {
            borrow = (uint64_t)r[i] - P_LIMBS[i] - borrow;
            tmp[i] = (uint32_t)borrow;
            borrow = (borrow >> 63) & 1;
        }
        #pragma unroll
        for (int i = 0; i < 8; i++) r[i] = tmp[i];
    }
}

__device__ void sqr_mod_p(const uint32_t* a, uint32_t* r) {
    mul_mod_p(a, a, r);
}

__device__ void point_add_jacobian(
    const uint32_t* X1, const uint32_t* Y1, const uint32_t* Z1,
    const uint32_t* X2, const uint32_t* Y2, const uint32_t* Z2,
    uint32_t* X3, uint32_t* Y3, uint32_t* Z3)
{
    if (is_zero(Z1)) {
        #pragma unroll
        for (int i = 0; i < 8; i++) {
            X3[i] = X2[i]; Y3[i] = Y2[i]; Z3[i] = Z2[i];
        }
        return;
    }
    if (is_zero(Z2)) {
        #pragma unroll
        for (int i = 0; i < 8; i++) {
            X3[i] = X1[i]; Y3[i] = Y1[i]; Z3[i] = Z1[i];
        }
        return;
    }
    
    uint32_t U1[8], U2[8], S1[8], S2[8], H[8], R[8];
    uint32_t Z1Z1[8], Z2Z2[8], tmp[8];
    
    sqr_mod_p(Z1, Z1Z1);
    sqr_mod_p(Z2, Z2Z2);
    mul_mod_p(X1, Z2Z2, U1);
    mul_mod_p(X2, Z1Z1, U2);
    mul_mod_p(Z2, Z2Z2, tmp);
    mul_mod_p(Y1, tmp, S1);
    mul_mod_p(Z1, Z1Z1, tmp);
    mul_mod_p(Y2, tmp, S2);
    
    sub_mod_p(U2, U1, H);
    sub_mod_p(S2, S1, R);
    
    if (is_zero(H)) {
        if (is_zero(R)) {
            uint32_t Y1Sq[8], S[8], M[8];
            sqr_mod_p(Y1, Y1Sq);
            mul_mod_p(X1, Y1Sq, S);
            add_mod_p(S, S, S); add_mod_p(S, S, S);
            sqr_mod_p(X1, tmp);
            add_mod_p(tmp, tmp, M);
            add_mod_p(M, tmp, M);
            sqr_mod_p(M, X3);
            sub_mod_p(X3, S, X3); sub_mod_p(X3, S, X3);
            sub_mod_p(S, X3, tmp);
            mul_mod_p(M, tmp, Y3);
            sqr_mod_p(Y1Sq, tmp);
            add_mod_p(tmp, tmp, tmp);
            add_mod_p(tmp, tmp, tmp);
            add_mod_p(tmp, tmp, tmp);
            sub_mod_p(Y3, tmp, Y3);
            mul_mod_p(Y1, Z1, Z3);
            add_mod_p(Z3, Z3, Z3);
            return;
        } else {
            #pragma unroll
            for (int i = 0; i < 8; i++) X3[i] = Y3[i] = Z3[i] = 0;
            return;
        }
    }
    
    uint32_t H2[8], H3[8], U1H2[8];
    sqr_mod_p(H, H2);
    mul_mod_p(H, H2, H3);
    mul_mod_p(U1, H2, U1H2);
    
    sqr_mod_p(R, X3);
    sub_mod_p(X3, H3, X3);
    sub_mod_p(X3, U1H2, X3);
    sub_mod_p(X3, U1H2, X3);
    
    sub_mod_p(U1H2, X3, tmp);
    mul_mod_p(R, tmp, Y3);
    mul_mod_p(S1, H3, tmp);
    sub_mod_p(Y3, tmp, Y3);
    
    mul_mod_p(Z1, Z2, Z3);
    mul_mod_p(Z3, H, Z3);
}

__device__ void jacobian_to_affine(
    const uint32_t* X, const uint32_t* Y, const uint32_t* Z,
    uint32_t* ax, uint32_t* ay)
{
    if (is_zero(Z)) {
        #pragma unroll
        for (int i = 0; i < 8; i++) ax[i] = ay[i] = 0;
        return;
    }
    uint32_t Zinv[8], Zinv2[8], Zinv3[8];
    #pragma unroll
    for (int i = 0; i < 8; i++) Zinv[i] = Z[i];
    sqr_mod_p(Zinv, Zinv2);
    mul_mod_p(Zinv, Zinv2, Zinv3);
    mul_mod_p(X, Zinv2, ax);
    mul_mod_p(Y, Zinv3, ay);
}

__device__ void scalar_mul_G(const uint32_t* k, uint32_t* rx, uint32_t* ry) {
    uint32_t Jx[8], Jy[8], Jz[8];
    uint32_t Gx[8], Gy[8], Gz[8];
    
    #pragma unroll
    for (int i = 0; i < 8; i++) {
        Jx[i] = Jy[i] = Jz[i] = 0;
        Gx[i] = GX_LIMBS[i];
        Gy[i] = GY_LIMBS[i];
        Gz[i] = (i == 0) ? 1 : 0;
    }
    
    for (int word = 7; word >= 0; word--) {
        for (int bit = 31; bit >= 0; bit--) {
            if (!is_zero(Jz)) {
                uint32_t tx[8], ty[8], tz[8];
                point_add_jacobian(Jx, Jy, Jz, Jx, Jy, Jz, tx, ty, tz);
                #pragma unroll
                for (int i = 0; i < 8; i++) {
                    Jx[i] = tx[i]; Jy[i] = ty[i]; Jz[i] = tz[i];
                }
            }
            if ((k[word] >> bit) & 1) {
                if (is_zero(Jz)) {
                    #pragma unroll
                    for (int i = 0; i < 8; i++) {
                        Jx[i] = Gx[i]; Jy[i] = Gy[i]; Jz[i] = Gz[i];
                    }
                } else {
                    uint32_t tx[8], ty[8], tz[8];
                    point_add_jacobian(Jx, Jy, Jz, Gx, Gy, Gz, tx, ty, tz);
                    #pragma unroll
                    for (int i = 0; i < 8; i++) {
                        Jx[i] = tx[i]; Jy[i] = ty[i]; Jz[i] = tz[i];
                    }
                }
            }
        }
    }
    jacobian_to_affine(Jx, Jy, Jz, rx, ry);
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN KANGAROO WALK KERNEL
// ═══════════════════════════════════════════════════════════════════════════════

__global__ void kangaroo_walk_kernel(
    WalkerState* walkers,
    const JumpPoint* jumps,
    uint32_t* found_flag,
    uint32_t* result_k,
    uint64_t max_steps,
    uint64_t* total_steps,
    uint32_t* dp_count,
    uint64_t* progress_counter  // Host-visible progress
) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid >= TOTAL_WALKERS) return;
    
    WalkerState* w = &walkers[tid];
    uint64_t step = 0;
    
    uint32_t wx[8], wy[8], wk[8];
    #pragma unroll
    for (int i = 0; i < 8; i++) {
        wx[i] = w->x[i];
        wy[i] = w->y[i];
        wk[i] = w->k[i];
    }
    
    for (step = 0; step < max_steps && !(*found_flag); step++) {
        int jump_idx = wx[0] & (N_JUMPS - 1);
        const JumpPoint* jp = &jumps[jump_idx];
        
        uint32_t new_x[8], new_y[8];
        uint32_t one[8] = {1,0,0,0,0,0,0,0};
        uint32_t jz[8] = {1,0,0,0,0,0,0,0};
        point_add_jacobian(wx, wy, one, jp->x, jp->y, jz, new_x, new_y, jz);
        
        #pragma unroll
        for (int i = 0; i < 8; i++) {
            wx[i] = new_x[i];
            wy[i] = new_y[i];
        }
        
        uint32_t jump_k[8] = {0};
        set_bit(jump_k, JUMP_BASE_BIT + jump_idx);
        
        if (w->ktype == 0) {
            add_mod_n(wk, jump_k, wk);
        } else {
            sub_mod_n(wk, jump_k, wk);
        }
        
        if ((wx[0] & DP_MASK) == 0) {
            atomicAdd(dp_count, 1);
            w->dp_count++;
        }
        
        if (u256_eq(wx, TARGET_X) && u256_eq(wy, TARGET_Y)) {
            if (atomicCAS(found_flag, 0, 1) == 0) {
                #pragma unroll
                for (int i = 0; i < 8; i++) {
                    result_k[i] = wk[i];
                }
            }
            break;
        }
        
        // Progress reporting (thread 0 only, every PROGRESS_INTERVAL steps)
        if (tid == 0 && (step % PROGRESS_INTERVAL) == 0) {
            atomicAdd(progress_counter, (uint64_t)PROGRESS_INTERVAL);
        }
    }
    
    // Final progress update
    if (tid == 0) {
        atomicAdd(progress_counter, (uint64_t)(step % PROGRESS_INTERVAL));
    }
    
    #pragma unroll
    for (int i = 0; i < 8; i++) {
        w->x[i] = wx[i];
        w->y[i] = wy[i];
        w->k[i] = wk[i];
    }
    w->steps += step;
    total_steps[tid] = step;
}

__global__ void init_jump_table_kernel(JumpPoint* jumps) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid >= N_JUMPS) return;
    
    JumpPoint* jp = &jumps[tid];
    uint32_t k[8] = {0};
    set_bit(k, JUMP_BASE_BIT + tid);
    scalar_mul_G(k, jp->x, jp->y);
}

__global__ void init_walkers_kernel(
    WalkerState* walkers,
    const uint32_t* range_lo,
    const uint32_t* range_hi)
{
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid >= TOTAL_WALKERS) return;
    
    WalkerState* w = &walkers[tid];
    int is_tame = (tid & 1);
    
    if (is_tame) {
        uint32_t k[8] = {0};
        for (int i = 0; i < 8; i++) k[i] = range_lo[i];
        
        uint64_t offset = (uint64_t)tid * 0x1000000ULL;
        uint32_t offset_limbs[8] = {0};
        offset_limbs[0] = (uint32_t)offset;
        offset_limbs[1] = (uint32_t)(offset >> 32);
        
        add_mod_n(k, offset_limbs, w->k);
        w->ktype = 0;
        scalar_mul_G(w->k, w->x, w->y);
    } else {
        #pragma unroll
        for (int i = 0; i < 8; i++) {
            w->k[i] = 0;
            w->x[i] = TARGET_X[i];
            w->y[i] = TARGET_Y[i];
        }
        w->ktype = 1;
    }
    
    w->steps = 0;
    w->dp_count = 0;
    #pragma unroll
    for (int i = 0; i < 5; i++) w->pad[i] = 0;
}
'''

def compile_and_load_kernel():
    """Compile CUDA kernel and return module."""
    cuda.init()
    device = cuda.Device(0)
    context = device.make_context()
    
    name = device.name()
    cc = device.compute_capability()
    arch = f'sm_{cc[0]}{cc[1]}'
    
    print(f"[CUDA] Device: {name}")
    print(f"[CUDA] Compute Capability: {cc[0]}.{cc[1]}")
    print(f"[CUDA] Architecture: {arch}")
    print(f"[CUDA] Total Memory: {device.total_memory() / 1e9:.2f} GB")
    
    try:
        mod = compiler.SourceModule(
            CUDA_KERNEL,
            options=['-O3', '-use_fast_math', f'-arch={arch}'],
        )
        print("[CUDA] Kernel compiled successfully")
    except Exception as e:
        print(f"[CUDA] Compilation error: {e}")
        raise
    
    return mod, cuda, context


def pack_uint256(value: int) -> np.ndarray:
    limbs = np.zeros(8, dtype=np.uint32)
    for i in range(8):
        limbs[i] = (value >> (32 * i)) & 0xFFFFFFFF
    return limbs


def unpack_uint256(limbs: np.ndarray) -> int:
    value = 0
    for i in range(8):
        value |= int(limbs[i]) << (32 * i)
    return value


class ProgressMonitor:
    """Monitor GPU progress in background thread."""
    
    def __init__(self, d_progress, total_steps, cuda, context):
        self.d_progress = d_progress
        self.total_steps = total_steps
        self.cuda = cuda
        self.context = context
        self.running = False
        self.last_progress = 0
        self.start_time = None
        self.thread = None
    
    def start(self):
        self.running = True
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._monitor_loop)
        self.thread.daemon = True
        self.thread.start()
    
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
    
    def _monitor_loop(self):
        while self.running:
            time.sleep(2)  # Check every 2 seconds
            
            try:
                progress = np.zeros(1, dtype=np.uint64)
                self.cuda.memcpy_dtoh(progress, self.d_progress)
                current = progress[0]
                
                if current > self.last_progress:
                    elapsed = time.time() - self.start_time
                    rate = current / elapsed / 1e6
                    pct = (current / self.total_steps) * 100
                    
                    # Clear line and print progress
                    sys.stdout.write(f"\r[CUDA] Progress: {current:,} / {self.total_steps:,} steps ({pct:.2f}%) | Rate: {rate:.2f} M steps/sec | Elapsed: {elapsed:.0f}s")
                    sys.stdout.flush()
                    
                    self.last_progress = current
            except Exception:
                pass


def solve_with_cuda(target_x: int = None, max_steps: int = None, 
                    range_lo: int = None, range_hi: int = None) -> int | None:
    """Full GPU solver for ECDLP using PyCUDA."""
    
    PUZZLE_TARGET_X = 0x145d2611c823a396ef6712ce0f712f09b9b4f3135e3e0aa3230fb9b6d08d1e16
    RANGE_LO = 0x40000000000000000000000000000000
    RANGE_HI = 0x80000000000000000000000000000000
    MAX_STEPS = 10000000  # 10M steps for testing (~30 seconds on T4)
    
    if target_x is None:
        target_x = PUZZLE_TARGET_X
    if max_steps is None:
        max_steps = MAX_STEPS
    if range_lo is None:
        range_lo = RANGE_LO
    if range_hi is None:
        range_hi = RANGE_HI
    
    print(f"\n[CUDA] ═══════════════════════════════════════════════════════════════")
    print(f"[CUDA] FULL SOLVER MODE - Puzzle #135")
    print(f"[CUDA] ═══════════════════════════════════════════════════════════════")
    print(f"[CUDA] Target: 0x{target_x:064x}")
    print(f"[CUDA] Range:  [0x{range_lo:064x}, 0x{range_hi:064x})")
    print(f"[CUDA] Max steps per walker: {max_steps:,}")
    
    mod, cuda_driver, context = compile_and_load_kernel()
    
    try:
        N_BLOCKS = 160
        N_THREADS = 256
        TOTAL_WALKERS = N_BLOCKS * N_THREADS
        N_JUMPS = 32
        
        total_steps_global = TOTAL_WALKERS * max_steps
        
        print(f"[CUDA] Launching {TOTAL_WALKERS:,} walkers ({N_BLOCKS} blocks x {N_THREADS} threads)")
        print(f"[CUDA] Total steps: {total_steps_global:,}")
        print(f"[CUDA] Estimated time: ~{total_steps_global / 100e6:.1f} seconds at 100M steps/sec")
        
        init_jumps_kernel = mod.get_function("init_jump_table_kernel")
        init_walkers_kernel = mod.get_function("init_walkers_kernel")
        walk_kernel = mod.get_function("kangaroo_walk_kernel")
        
        range_lo_limbs = pack_uint256(range_lo)
        range_hi_limbs = pack_uint256(range_hi)
        
        d_walkers = cuda_driver.mem_alloc(TOTAL_WALKERS * 128)
        d_jumps = cuda_driver.mem_alloc(N_JUMPS * 64)
        d_range_lo = cuda_driver.mem_alloc(32)
        d_range_hi = cuda_driver.mem_alloc(32)
        d_found = cuda_driver.mem_alloc(4)
        d_result = cuda_driver.mem_alloc(32)
        d_total_steps = cuda_driver.mem_alloc(TOTAL_WALKERS * 8)
        d_dp_count = cuda_driver.mem_alloc(4)
        d_progress = cuda_driver.mem_alloc(8)
        
        cuda_driver.memcpy_htod(d_range_lo, range_lo_limbs)
        cuda_driver.memcpy_htod(d_range_hi, range_hi_limbs)
        cuda_driver.memset_d32(d_found, 0, 1)
        cuda_driver.memset_d32(d_dp_count, 0, 1)
        cuda_driver.memset_d32(d_progress, 0, 2)
        
        print("[CUDA] Initializing jump table...")
        init_jumps_kernel(d_jumps, block=(N_JUMPS, 1, 1), grid=(1, 1))
        
        print("[CUDA] Initializing walkers...")
        init_walkers_kernel(
            d_walkers, d_range_lo, d_range_hi,
            block=(N_THREADS, 1, 1), grid=(N_BLOCKS, 1)
        )
        
        context.synchronize()
        print("[CUDA] Initialization complete")
        
        # Start progress monitor
        monitor = ProgressMonitor(d_progress, total_steps_global, cuda_driver, context)
        monitor.start()
        
        print(f"[CUDA] Launching kangaroo walk kernel...")
        start_time = time.time()
        
        walk_kernel(
            d_walkers, d_jumps, d_found, d_result,
            np.uint64(max_steps),
            d_total_steps, d_dp_count, d_progress,
            block=(N_THREADS, 1, 1), grid=(N_BLOCKS, 1),
            shared=0
        )
        
        context.synchronize()
        monitor.stop()
        
        elapsed = time.time() - start_time
        print(f"\n[CUDA] Kernel completed in {elapsed:.2f}s")
        
        # Get final stats
        total_steps_host = np.zeros(TOTAL_WALKERS, dtype=np.uint64)
        cuda_driver.memcpy_dtoh(total_steps_host, d_total_steps)
        total_steps = np.sum(total_steps_host)
        rate = total_steps / elapsed / 1e6
        print(f"[CUDA] Total steps: {total_steps:,}")
        print(f"[CUDA] Throughput: {rate:.2f} M steps/sec")
        
        found = np.zeros(1, dtype=np.uint32)
        cuda_driver.memcpy_dtoh(found, d_found)
        
        dp_count = np.zeros(1, dtype=np.uint32)
        cuda_driver.memcpy_dtoh(dp_count, d_dp_count)
        print(f"[CUDA] Distinguished points: {dp_count[0]:,}")
        
        if found[0]:
            result_limbs = np.zeros(8, dtype=np.uint32)
            cuda_driver.memcpy_dtoh(result_limbs, d_result)
            k = unpack_uint256(result_limbs)
            print(f"\n[CUDA] ✓✓✓ SOLUTION FOUND ✓✓✓")
            print(f"[CUDA] k = 0x{k:064x}")
            return k
        else:
            print("[CUDA] No solution found in this run")
            return None
            
    except Exception as e:
        print(f"\n[CUDA] Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        context.pop()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="PyCUDA ECDLP Solver")
    parser.add_argument("--steps", type=int, default=10000000, 
                       help="Steps per walker (default: 10M, ~30 sec)")
    parser.add_argument("--continuous", action="store_true",
                       help="Run continuously until solution found")
    args = parser.parse_args()
    
    if args.continuous:
        iteration = 0
        while True:
            iteration += 1
            print(f"\n{'='*60}")
            print(f"Iteration {iteration}")
            print(f"{'='*60}")
            
            result = solve_with_cuda(max_steps=args.steps)
            if result:
                print(f"\n*** SOLUTION FOUND AFTER {iteration} ITERATIONS: {hex(result)} ***")
                break
            
            print(f"\nRestarting for next iteration...\n")
            time.sleep(1)
    else:
        result = solve_with_cuda(max_steps=args.steps)
        if result:
            print(f"\n*** SOLUTION: {hex(result)} ***")
        else:
            print("\nNo solution found")
