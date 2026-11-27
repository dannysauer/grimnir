# Design: how does sensing get from one-room classification to occupancy, sleep, and respiration?

> **Summary:** The goals run from room-level location of people, through
> pets and sleep, to respiration and telling people apart. The leading option
> is to fix what the system measures and how labels and evaluation work
> before investing in models, and to use Bluetooth rather than CSI for
> identity. Nothing here has been measured on the real house yet, so the
> first step is to collect that evidence.

## Record

| Field | Value |
| --- | --- |
| Date | 2026-11-15 |
| Status | Draft |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Related | Review epic [#102](https://github.com/dannysauer/grimnir/issues/102); capture [#112](https://github.com/dannysauer/grimnir/issues/112), [#66](https://github.com/dannysauer/grimnir/issues/66); labels [#107](https://github.com/dannysauer/grimnir/issues/107), [#14](https://github.com/dannysauer/grimnir/issues/14); scoring [#111](https://github.com/dannysauer/grimnir/issues/111), [#61](https://github.com/dannysauer/grimnir/issues/61); location [#110](https://github.com/dannysauer/grimnir/issues/110), [#87](https://github.com/dannysauer/grimnir/issues/87); phase [#7](https://github.com/dannysauer/grimnir/issues/7); [ML pipeline](../architecture/ml-pipeline.md); [data model](../architecture/data-model.md) |

## Problem

Grimnir can name one occupied room from per-window amplitude statistics. The
[goals](../architecture/overview.md#purpose) go much further: several people,
pets, the wider property, sleep, respiration, and identity.

A code review on 2026-11-15
([#102](https://github.com/dannysauer/grimnir/issues/102)) found that the
limits aren't mainly in the
classifier. They're in what gets captured, what a label can say, and how a
model is scored:

- A sample's stored time is when Geri parsed it. The capture timestamp is
  discarded, and no sequence number exists, so sampling jitter and packet
  loss can't be measured.
- The CSI buffer's contents change with the frame format, and nothing in the
  packet says which format arrived. The reported antenna count is wrong
  ([#66](https://github.com/dannysauer/grimnir/issues/66)).
- Huginn transmits ordinary Wi-Fi traffic through the access point at roughly
  10 Hz, so neither the rate nor the frame format is controlled.
- A label is one room and a count. It can't hold two people in two rooms, a
  pet, a named person, or "asleep".
- Models are scored on a random split of near-identical windows, so the
  reported accuracy says little about tomorrow
  ([#61](https://github.com/dannysauer/grimnir/issues/61)).

If nothing changes, more labeling and a different classifier will produce
better numbers on the dashboard and the same behavior in the house.

## Goals and non-goals

Goals:

- An order of work in which each step is useful by itself and makes the next
  goal reachable.
- An honest statement of which goals this hardware can probably meet.
- A way to know, with evidence, whether a step worked.

Non-goals:

- Choosing a model family. That follows from evaluation, once evaluation can
  be trusted.
- Authentication and the agent interface. See
  [#5](https://github.com/dannysauer/grimnir/issues/5) and the
  [agent training interface](2026-11-15-agent-training-interface.md) doc.

## Requirements in scope

- `GRM-001`: Geri accepts every packet version still flashed, so a new packet
  format has to arrive as a new version beside the old ones.
- `GRM-012`: labeled CSI is never expired, so a new label model has to carry
  the existing training set forward or say plainly that it's being retired.
- `GRM-022` and `GRM-023`: one shared feature extractor, and a model that
  declares the feature version it needs.
- `GRM-033`: training and inference reach data only through Freki.

No requirement states an accuracy, latency, or coverage target. This work
needs a few, and they should go on the requirements page with real IDs once
the first measurements exist. Candidates, with the numbers left open on
purpose:

- Room-level accuracy for one moving person, scored on days the model never
  saw.
- False-occupancy rate over hours when the house is known to be empty.
- Time from entering a room to the prediction changing.
- Fraction of transmitted frames that reach the database, per receiver.

## Constraints

- [Train and infer in separate services that reach data only through Freki](../adrs/2026-04-18-ml-services-use-freki-api.md).
- [Share one versioned feature extractor](../adrs/2026-04-18-shared-versioned-feature-extraction.md).
  A pipeline with filtering and spectral steps outgrows a single integer
  version, so that record probably needs a successor.
- [Keep labeled CSI in its own hypertable and expire raw CSI after 14 days](../adrs/2026-04-13-separate-training-samples-retention.md).
  Unlabeled history older than 14 days doesn't exist.
- [Carry CSI over a versioned binary UDP protocol](../adrs/2026-04-19-udp-wire-protocol-with-ack-liveness.md).
- The receivers are ESP32-S3 boards with one receive chain. Methods that
  compare antennas, such as conjugate multiplication, aren't available.
- One person labels from a phone. Any label model has to stay quick to use.

## Options

### Keep the current approach

Collect more labels, add `empty` sessions, and tune the random forest.

This costs the least and helps the first goal a little. It doesn't address
any of the five findings above. Mean amplitude per subcarrier is a fingerprint
of the room's furniture and the radio's gain state as much as of the person,
so I'd expect it to drift across days; that's a judgment from the literature,
not a measurement here. The later goals stay out of reach because the labels
can't describe them and the features discard the time series.

### Model first

Move straight to a neural network over raw amplitude sequences, which was
step 3 of the original plan in
[#9](https://github.com/dannysauer/grimnir/issues/9).

A sequence model can learn motion patterns that window statistics miss. But
it would train on the same jittered, unlabeled-format samples, be scored by
the same leaky split, and predict the same single-room labels. It would also
need far more labeled data than exists. It's the right move later and the
wrong first move.

### Measurement first

Fix the instrument, then the labels, then the scoring, then the models. In
order:

1. **Capture.** A version 3 packet that carries raw I/Q, the frame format,
   a per-receiver sequence number, a 64-bit capture timestamp, and a drop
   counter. Huginn sends a fixed-format frame on a timer at a rate that can
   be raised. Geri stores the device timestamp and exposes loss as a metric.
2. **Labels.** Subjects (a person or a pet), places, and annotations that say
   which subject was where and doing what over a time range. Sessions where
   the whole house's occupancy is known, so "empty" is a fact and not a room.
3. **Scoring.** Hold out whole sessions and whole days. Store a confusion
   matrix and per-class results with each model, tied to the exact data it
   saw.
4. **Location.** One feature vector across all links per time step, a real
   empty state, smoothing over time, and a prediction that expires when
   Völva stops.
5. **Sleep.** A derived state: in a bedroom, little motion for some minutes,
   at a plausible hour.
6. **Respiration.** A dedicated link across the bed at 20 Hz or more, a
   band-pass filter over 0.1 to 0.5 Hz, and a spectral peak.

Each step ships alone. Steps 1 to 3 change nothing a person sees, and
everything after depends on them.

The cost is real: a firmware protocol change and a reflash of every board, a
schema migration that touches the label code with the most bug history, and a
dashboard labeling flow that has to capture more without getting slower.

### Add a second signal for the hard goals

Use Bluetooth for identity and pets, and keep CSI for presence and motion.
The ESP32-S3 boards already have Bluetooth radios, so a receiver could report
which known phones, watches, and collar tags it hears.

Telling people apart from CSI alone is research-grade. Published gait
identification uses multi-antenna cards at around 1 kHz in fixed walkways, and
it doesn't hold across days. A phone in a pocket answers the same question
directly. A stationary pet is close to invisible to CSI, and a collar tag
isn't.

This option doesn't replace measurement first. It changes what CSI is asked
to do: "something moved here" from CSI, "who or what it was" from Bluetooth.
A millimetre-wave presence sensor beside a bed is a similar shortcut for
sleep and respiration, at the price of new hardware per bed.

## Comparison

Rows where every option scores the same are left out. The confidence figures
are the reviewer's rough estimates for ESP32-S3 hardware, not measurements.

| | Keep current | Model first | Measurement first | Plus a second signal |
| --- | --- | --- | --- | --- |
| One moving person, room level, holding up across days | Unlikely | Unlikely | Likely, about 80% | Same as measurement first |
| Empty house reported as empty | No | No | Yes | Yes |
| Two people in different rooms | No | No | Plausible, 50 to 60% | Better, when both carry a tag |
| Pets as their own class | No | No | Weak, 20 to 40% | Likely with collar tags |
| Asleep, and where | No | No | Plausible with a link across the bed | Likely with a bedside sensor |
| Respiration rate | No | No | Plausible for one sleeper with a dedicated link | Likely with a bedside sensor |
| Which person | No | No | Unlikely, under 15% | Likely for anyone carrying a phone or watch |
| Reflash every board | No | No | Yes | Yes, for Bluetooth scanning |
| Keeps `GRM-012` without a migration of the training set | Yes | Yes | No, the old set needs a mapping or retirement | No |

## Recommendation

Measurement first, with Bluetooth added for identity and pets when those
goals come up.

I'm fairly confident about the order and much less confident about the
numbers. The order follows from the code: no model can recover a timestamp
that was thrown away or a label that was never recorded. The numbers come
from published work on other hardware in other buildings.

Three things would change this recommendation. If the existing model already
holds up on held-out days, the capture work matters less for the first goal
and can wait until respiration. If a fixed-format transmit turns out not to
work alongside the access point, the capture step needs a different plan. And
if nobody in the house will carry a tag, identity is off the table rather
than moved to Bluetooth.

## Open questions

- **How well does the current model do on days it never saw?** Retrain on the
  existing `training_samples` with whole days held out, and file the result as
  an evidence receipt.
- **Do CSI rows in the database vary in length?** Count
  `array_length(amplitude, 1)` by receiver over the stored data. One query.
- **What rate actually arrives, and how much is lost?** Unknown until packets
  carry a sequence number. A one-off capture with a sequence in the payload
  would give a first number.
- **Can Huginn send fixed-format frames on a timer while the receivers stay
  associated to the access point?** A firmware spike with ESP-NOW or
  `esp_wifi_80211_tx` on one transmitter and one receiver.
- **Is breathing visible at all on this hardware?** A spike with one
  transmitter and one receiver a metre or two apart across a bed, logging
  raw I/Q at 20 Hz or more for one night.
- **How many links does the house need?** Unknown. One transmitter and two
  receivers give two links. Every node transmitting in turn would give many
  more from the same boards.
- **Does the existing training set carry forward?** It depends on whether
  old labels map cleanly onto the new annotation model. The owner decides
  whether to migrate or retire it.

## Outcome

Open. No changes of direction yet.
