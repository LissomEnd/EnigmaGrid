# Native mapped-memory regression checks

The test replaces four Vulkan driver entry points but uses the production
`host_memory.h` helper. It checks memory-type eligibility and coherent preference,
whole-allocation mapping, flush after host writes, invalidation before host reads,
and unmapping when synchronization fails. A failed map must not be unmapped.
It does not exercise a real GPU, fence execution, or a noncoherent physical driver.
The backend retains its shader-to-host barrier and waits for the submission fence
before calling the read helper.

On a Linux host with a C++17 compiler and Vulkan development headers (no Vulkan
runtime or GPU required):

```sh
c++ -std=c++17 android/native-tests/host_memory_checks.cpp -o /tmp/host-memory-checks
/tmp/host-memory-checks
```

Alternatively compile an Android command-line test with an installed NDK:

```sh
$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android26-clang++ \
  -std=c++17 -static-libstdc++ android/native-tests/host_memory_checks.cpp \
  -o /tmp/host-memory-checks
```

Run that executable only on an authorized Android test device. This is not an APK
and does not replace the installed app. Native source compile checks for supported
ABIs use the matching NDK `aarch64-linux-android26-clang++`,
`armv7a-linux-androideabi26-clang++`, and `x86_64-linux-android26-clang++` commands
with `-std=c++17 -fsyntax-only android/app/src/main/cpp/vulkan_rows.cpp`.
On Windows use `windows-x86_64` and the `.cmd` compiler wrappers.

References:
- [Flush and unmap semantics](https://docs.vulkan.org/refpages/latest/refpages/source/vkFlushMappedMemoryRanges.html)
- [Whole-allocation mapped range alignment](https://docs.vulkan.org/refpages/latest/refpages/source/VkMappedMemoryRange.html)
- [Invalidate semantics](https://docs.vulkan.org/refpages/latest/refpages/source/vkInvalidateMappedMemoryRanges.html)
