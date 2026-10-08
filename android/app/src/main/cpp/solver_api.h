#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef _WIN32
#define ENIGMAGRID_EXPORT __declspec(dllexport)
#else
#define ENIGMAGRID_EXPORT __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif
/* Same bounded solver and sparse result layout as Android JNI. Returns zero
 * on success; no exceptions cross the ABI. Buffers remain caller-owned.
 * capacity/written count uint32_t words, errorCapacity counts bytes. */
ENIGMAGRID_EXPORT int enigmagrid_solve(
    const uint32_t* input,size_t inputCount,const uint32_t* code,size_t codeCount,
    uint32_t* output,size_t capacity,size_t* written,char* error,size_t errorCapacity);
#ifdef __cplusplus
}
#endif
