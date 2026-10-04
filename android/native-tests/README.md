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

## Real GPU row parity without installing an APK

`real_gpu_checks.cpp` includes the production backend and executes its actual
`Compute::run` implementation. `NativeRowFixtures.java` generates CPU reference
data for batches of 1, 2 and 16 keys with window lengths 1, 2, 3, 16, 71 and 72,
ending at position 72. Three passes reuse the same native compute object. This
checks 54 dispatches and 244,530 contacts; it is not a throughput benchmark or
full app lifecycle test.

Example preparation from the repository root on Linux with Java 17 and an NDK:

```sh
mkdir -p /tmp/enigmagrid-native/classes
javac -d /tmp/enigmagrid-native/classes android/core/src/main/java/org/enigmagrid/core/*.java android/native-tests/NativeRowFixtures.java
java -cp /tmp/enigmagrid-native/classes NativeRowFixtures /tmp/enigmagrid-native/fixtures.txt
$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android26-clang++ \
  -std=c++17 -static-libstdc++ android/native-tests/real_gpu_checks.cpp \
  -lvulkan -o /tmp/enigmagrid-native/real-gpu-checks
```

Use the `enigma_rows.comp.spv` generated from this checkout's shader by the Android
build, for example under `app/build/intermediates/assets/release/mergeReleaseAssets/shaders/`
inside `android`. Copy the executable, shader and fixtures to an authorized test
device's temporary directory. Run `timeout -k 2 25 EXECUTABLE SHADER FIXTURES`
through ADB, then remove those three temporary files. Do not run multiple driver
tests concurrently. A timeout or mismatch is a failed qualification, not permission
to bypass the device's resource controls.

The current test passed on RedMagic's Adreno 830 with coherent input and output
memory. This does not qualify other drivers or physical non-coherent memory.

References:
- [Flush and unmap semantics](https://docs.vulkan.org/refpages/latest/refpages/source/vkFlushMappedMemoryRanges.html)
- [Whole-allocation mapped range alignment](https://docs.vulkan.org/refpages/latest/refpages/source/VkMappedMemoryRange.html)
- [Invalidate semantics](https://docs.vulkan.org/refpages/latest/refpages/source/vkInvalidateMappedMemoryRanges.html)
