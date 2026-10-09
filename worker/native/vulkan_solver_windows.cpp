// Windows DLL translation unit. Keep the shared Android solver source unchanged.
#include "../../android/app/src/main/cpp/vulkan_solver.cpp"

// Call only after every solver owner has joined; the native solver cache is
// process-global and the same cache is reused by every NativeSolver object.
extern "C" ENIGMAGRID_EXPORT int enigmagrid_close() {
    try {
        std::lock_guard<std::mutex> lock(computeMutex);
        cachedSolverCompute.reset();
        cachedCode.clear();
        return 0;
    } catch(...) {return -1;}
}
