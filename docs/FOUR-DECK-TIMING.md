# First timing correction and the missing enlarged waveforms

2026-11-04. Ronald confirms four simultaneous tracks on separate mixer channels.
He reports that beats drift apart after alignment and that only two enlarged
waveforms appear, even after selecting four-deck view. Four bottom overviews do
appear. Treat these as two defects to investigate separately.

## Reproduced timing failure

The existing phase tests run a synthetic USB sink at the same nominal rate as
the observation clock. A new experiment varies the USB rate relative to the
native/host clock while retaining a coherent synthetic native phase source.
It uses the real software player, queued PCM generation and completed source
tags. Its phase oracle uses the injected USB rate, independently of the player's
clock estimate. Both 44.1 and 48 kHz source media are tested.

With USB running 1,000 ppm slower (0.1%), the old mapping lets error grow from
about 2.6 ms at five seconds to 45.1 ms at 90 seconds, while reporting lock on
every sample after warmup. The mapping's lower envelope can rise only 0.5 ms per
second, so it cannot follow this injected 1 ms-per-second change. This proves a
software failure under the stated clock condition. The real XZ clock difference
has not been measured, so this is not yet a diagnosis of Ronald's hardware drift.

## Change

The USB worker now publishes the monotonic time at which it reaped the output
prefix, in the same cached snapshot as `wire_completed_frames`. The player uses
that paired observation to re-anchor its wire-to-host mapping. It therefore
does not accumulate a global nominal-rate error between the USB and CPU clocks.
Reading a cached snapshot later does not assign it a new timestamp.

The new field is `xz_usb_position.wire_observed_us`. It is a **host reap
observation**, not a device timestamp or acoustic/DAC measurement. Scheduling,
completion batching, downstream latency and native phase accuracy still matter.
Timestamp-less test sinks retain their previous fallback behavior. This change
does not reduce audio buffers, change jog sensitivity or alter cue/transport
semantics. The transport and player must be rebuilt together; the current build
links both into the same runtime.

Synthetic maximum absolute phase error, after five seconds of warmup:

| Injected USB rate error | 44.1 kHz source, before | 44.1 kHz source, after | 48 kHz source, after |
| --- | ---: | ---: | ---: |
| 0 ppm | 0.030 ms | 0.030 ms | 0.024 ms |
| -250 ppm | 0.067 ms | 0.067 ms | 0.066 ms |
| +250 ppm | 0.089 ms | 0.089 ms | 0.089 ms |
| -1,000 ppm | 45.106 ms | 0.249 ms | 0.248 ms |
| +1,000 ppm | 0.271 ms | 0.271 ms | 0.270 ms |

These are 90-second synthetic runs, not measured XZ audio. The new regression
requires error below 1 ms in each of the ten conditions. Discarding the new
timestamp reproduces the failure and is rejected by the host verifier.

Validation: all 16 Mac host checks pass, including the existing tempo-first
engine regressions, the new skew cases, and both rejected mutations. The two
changed production translation units also compile for ARM32 Cortex-A9 against
glibc 2.13 using Zig 0.16.0. That is object compilation, not a linked deployable
runtime or a hardware trial. Linux transport/connector checks run in CI.

Reproduce with `python3 tools/verify_four_deck.py --output NEW_DIRECTORY`.
The `sync-clock-skew.log` records measurements; `verification.json` records
source/include hashes and commands. `sync-clock-skew` runs with live assertions
and the selected sanitizer.

## Display evidence and the first trial

The returned USB's loader SHA-256 still matches the working baseline:
`0a3e2e9717b9a5a45e7c382f5dcd4956917b61cbb5ac9a67c0dbdf1d6d77d33b`.
Its settings select `interface=0` (Classic) and `deck_view=1` (four decks).
This supports the user's report that choosing four decks did not resolve it.

Classic's main waveform path uses `ui/native_wave_runtime.c` to capture and
transform a guarded 536 by 268 stock window. The bottom overviews are drawn
through a separate adapter. Modern uses the shell renderer. The saved USB log
shows successful bootstrap/runtime staging, but does not include
`/dev/shm/xz-mods.log`, which is volatile and was lost at power-off. It cannot
identify which main-wave guard or draw stage failed. Do not relax those guards
without actual render-state evidence.

The first USB display trial selects Modern (`interface=1`) and mixer-order
four-deck view (`deck_view=2`), preserving the other preferences. The serializer
also derives the compatible legacy theme value. This uses the existing renderer
and keeps the exact working audio runtime. It is a reversible alternate display
path, not a verified repair of the Classic hook. The loader, previous settings
and startup log were backed up with hash readback before the trial.

After boot, verify **four enlarged scrolling lanes**, then switch left 1/3 and
right 2/4 while all tracks play. A successful display trial does not validate
the timing patch, because that patch is not on this USB yet.

For the next timing comparison, first use the **same analysed WAV** on decks 1
and 3, with matching tempo, SYNC and QUANTIZE on. Note the master and whether the
offset stays fixed or grows. This distinguishes the player/clock problem from
different tracks' beat-grid or BPM errors. Repeat with the candidate runtime
only after its complete paired build and loader verification.
