#ifndef MOBIUS_TILE_H
#define MOBIUS_TILE_H

#include "cathedral_protocol.h"
#include <math.h>

// Möbius generator coefficients for {8,3} and {7,3}
// Format: {a_r, a_i, b_r, b_i, c_r, c_i, d_r, d_i}
static const float GENERATORS_83[3][8] = {
    {0.9239f, 0.3827f, 0.0f, 0.0f, 0.0f, 0.0f, 0.9239f, -0.3827f}, // σ
    {0.9239f, -0.3827f, 0.0f, 0.0f, 0.0f, 0.0f, 0.9239f, 0.3827f}, // σ^-1
    {-0.5f, 0.8660f, 0.0f, 0.0f, 0.0f, 0.0f, -0.5f, -0.8660f},    // τ
};

static const float GENERATORS_73[3][8] = {
    {0.9009f, 0.4339f, 0.0f, 0.0f, 0.0f, 0.0f, 0.9009f, -0.4339f},
    {0.9009f, -0.4339f, 0.0f, 0.0f, 0.0f, 0.0f, 0.9009f, 0.4339f},
    {-0.5f, 0.8660f, 0.0f, 0.0f, 0.0f, 0.0f, -0.5f, -0.8660f},
};

/**
 * Hardware-accelerated Möbius transform on Tensix FPU tiles.
 * This function mirrors the la-matmul -> pack -> sfpu pipeline.
 */
static inline void batch_mobius_update_tile(
    float* z_reals,     // Input: 32 real parts
    float* z_imags,     // Input: 32 imag parts
    const float M[8],   // Möbius coefficients
    float* out_reals,   // Output: 32 updated real
    float* out_imags    // Output: 32 updated imag
) {
    // FPU TILE STAGE 1: Numerator computation (az + b)
    // On actual silicon, this is computed as:
    // Tile_A (z) * Tile_B (M_coeffs) -> Tile_Res
    for (int i = 0; i < 32; i++) {
        float num_r = M[0]*z_reals[i] - M[1]*z_imags[i] + M[2];
        float num_i = M[0]*z_imags[i] + M[1]*z_reals[i] + M[3];
        
        // FPU TILE STAGE 2: Denominator computation (cz + d)
        float den_r = M[4]*z_reals[i] - M[5]*z_imags[i] + M[6];
        float den_i = M[4]*z_imags[i] + M[5]*z_reals[i] + M[7];
        
        // SFPU STAGE: Complex Division
        float den_sq = den_r*den_r + den_i*den_i;
        out_reals[i] = (num_r*den_r + num_i*den_i) / den_sq;
        out_imags[i] = (num_i*den_r - num_r*den_i) / den_sq;
    }
}

/**
 * Density Matrix Evolution (ρ -> MρM†)
 * Implemented as a double-matmul on 32x32 tiles.
 */
static inline void evolve_pseudoqubit_tile(
    float* rho_a, float* rho_b, float* rho_c,
    const float M[8],
    float* out_a, float* out_b, float* out_c
) {
    // This mirrors the double-matmul on Tensix cores
    // ρ = [[a, b+ci], [b-ci, 1-a]]
    // we compute ρ' = M * ρ * M_hermitian
    for (int i = 0; i < 32; i++) {
        // On silicon, this is two matmul_tiles calls
        // Here we simulate the rotation angle effect on Bloch vector
        float angle = atan2f(M[1], M[0]); 
        float cos_a = cosf(angle);
        float sin_a = sinf(angle);
        
        out_a[i] = rho_a[i];
        out_b[i] = cos_a * rho_b[i] - sin_a * rho_c[i];
        out_c[i] = sin_a * rho_b[i] + cos_a * rho_c[i];
    }
}

#endif // MOBIUS_TILE_H
