#ifndef CATHEDRAL_PROTOCOL_H
#define CATHEDRAL_PROTOCOL_H

#include <stdint.h>
#include <stdbool.h>

/**
 * ══════════════════════════════════════════════════════════════════════════════════════════
 * NOVA BOMBA: ABSOLUTE SILICON MEMORY MAP (N300 L1 SRAM)
 * ══════════════════════════════════════════════════════════════════════════════════════════
 * This map is the ground truth for all 160 Tensix cores. 
 * All offsets are absolute relative to the start of the 1.5MB L1 SRAM.
 */

// --- GDDR6 GLOBAL BASES ---
#define POINCARE_SPHERE_GDDR6_BASE 0x200000000ULL
#define JUMP_TABLE_GDDR6_BASE      0x300000000ULL
#define KANGAROO_INIT_STATES_BASE  0x400000000ULL
#define DP_CSV_BUFFER_GDDR6       0x2F0000000ULL

// --- L1 SRAM ABSOLUTE OFFSETS (The-Symmetry-Squeeze Map) ---
#define L1_PATCH_BASE            0x00000  // [0x00000..0x01C00)  -> PatchNode[113] (7,232B)
#define L1_KANGAROO_STATE       0x01C00  // [0x01C00..0x01F00)  -> KangarooState (256B)
#define L1_DP_RING_BUFFER       0x02000  // [0x02000..0x04000)  -> DP Ring (8KB)
#define L1_JUMP_TABLE           0x04000  // [0x04000..0x06000)  -> JumpPoint[32] (8KB)
#define L1_JUMP_SCALARS         0x06000  // [0x06000..0x07000)  -> Jump Scalars (4KB)
#define L1_MOBIUS_WORKSPACE     0x07000  // [0x07000..0x08000)  -> Möbius Tile Space (4KB)
#define L1_FPU_SCRATCH          0x08000  // [0x08000..0x0A000)  -> FPU Scratch (8KB)
#define L1_DQN_BIAS             0x0A000  // [0x0A000..0x0C000)  -> DQN Bias Scores (8KB)
#define L1_FIELD_ARITH_SQUEEZE  0x0C000  // [0x0C000..0x18000)  -> Z_p / p-adic limbs (48KB)
#define L1_BATCH_INV_SCRATCH    0x18000  // [0x18000..0x20000)  -> ModInv Scratch (32KB)
#define L1_BSGS_HOT_PAGE        0x20000  // [0x20000..0x30000)  -> BSGS Cache (64KB)
#define L1_ISOGENY_STATE        0x30000  // [0x30C00..0x40000)  -> Isogeny Chain (64KB)
#define L1_DP_FLOOD_BUFFER      0x40000  // [0x40000..0x60000)  -> DP Flood Buffer (128KB)
#define L1_Symmetry_SQUEEZE     0x60000  // [0x60000..0x80000)  -> LLL/CRT/Semaev (128KB)
#define L1_DEEP_ZONE_SRAM       0x80000  // [0x80000..0x180000) -> Deep Expansion (1MB)

// --- ARCHITECTURAL CONSTANTS ---
#define MAX_PATCH_NODES 121
#define N_JUMPS         32
#define GHOST_THREADS   8
#define BATCH_SIZE      32
#define DP_RING_SIZE_BYTES 8192

typedef struct {
    float z_real;           // 4B
    float z_imag;           // 4B
    float sphere_x;         // 4B
    float sphere_y;         // 4B
    float sphere_t;         // 4B
    uint64_t j_invariant;   // 8B
    uint16_t conj_class;    // 2B
    uint8_t  mckay_idx;    // 1B
    uint8_t  depth;         // 1B
    uint8_t  tess;          // 1B
    uint8_t  boundary_ring;// 1B
    float    rho_a;         // 4B
    float    rho_b;         // 4B
    float    rho_c;         // 4B
    float    fidelity;      // 4B
    uint32_t adj[4];        // 16B
    uint8_t  _pad[2];       // 2B (Align to 64B)
} PatchNode;

typedef struct {
    uint32_t walk_point_x[8];  // 32B
    uint32_t walk_point_y[8];  // 32B
    uint32_t k_offset[8];      // 32B
    uint8_t  ktype;            // 1B
    uint8_t  pair_id;           // 1B
    uint8_t  chain_id;          // 1B
    uint8_t  _pad[5];           // 5B
    float    poincare_z_real;  // 4B
    float    poincare_z_imag;  // 4B
    float    sphere_phi;       // 4B
    float    sphere_theta;      // 4B
    uint64_t j_invariant;       // 8B
    uint16_t conj_class;        // 2B
    uint8_t  depth;             // 1B
    uint8_t  tessellation;      // 1B
    uint8_t  boundary_ring;     // 1B
    uint8_t  _pad2[3];          // 3B
    float    rho_a;             // 4B
    float    rho_b;             // 4B
    float    rho_c;             // 4B
    float    fidelity;           // 4B
    uint32_t jump_table_offset;  // 4B
    uint32_t dp_threshold_bits;  // 4B
    uint64_t steps_since_dp;    // 8B
    uint64_t total_steps;       // 8B
    uint32_t patch_base_l1;     // 4B
    uint32_t patch_node_count;  // 4B
    uint32_t dp_ring_write_ptr;  // 4B
    uint32_t dp_ring_read_ptr;   // 4B
    uint8_t  _pad3[8];           // 8B (Align to 256B)
} KangarooState;

typedef struct {
    uint32_t x_limbs[8]; // 32B
    uint32_t y_limbs[8]; // 32B
} JumpPoint;

#endif // CATHEDRAL_PROTOCOL_H

