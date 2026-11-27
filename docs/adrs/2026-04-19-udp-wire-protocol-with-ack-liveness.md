# ADR: Carry CSI over a versioned binary UDP protocol with ACK liveness

## Record

| Field | Value |
| --- | --- |
| Date | 2026-04-19 |
| Status | Accepted |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Scope | How Muninn receivers deliver CSI samples to Geri and learn that Geri is listening. Excludes what a sample contains. |
| Related | [#41](https://github.com/dannysauer/grimnir/issues/41), [#44](https://github.com/dannysauer/grimnir/issues/44), [#40](https://github.com/dannysauer/grimnir/issues/40); commits `8e4515d`, `747eb3b`, and `645d80d`; [UDP wire protocol](../udp-wire-protocol.md) |
| Implementation | `firmware/muninn/main/main.c`, `geri/src/geri/parser.py`, `geri/src/geri/main.py` |

## Business driver

Receivers are unattended ESP32 boards in other rooms. On 2026-04-19 receivers
stopped reporting until someone restarted them
([#40](https://github.com/dannysauer/grimnir/issues/40)). The cause wasn't
recorded. What the outage showed is that a receiver had no way to tell that
its packets were going nowhere. The first packet format also
capped receiver names at 16 bytes, too short for location-based names such as
`grimnir-rx-office-west`.

## Constraints

- Boards already flashed with the old format keep running until someone
  reflashes them by hand.
- UDP gives the sender no delivery signal.
- A lost CSI sample costs little. A stalled sender costs everything.

## Decision

**Y statement:** We will send one little-endian binary datagram per CSI
sample, with a version field in the header, and have Geri answer with a
periodic `grimnir-ack` datagram that Muninn treats as its liveness signal,
because unattended receivers have to notice a dead path and recover alone, so
a stalled receiver repairs its own connection instead of waiting for a person.

Version 2 widens the receiver name to 32 bytes and the header to 60 bytes.
The layout is in the [UDP wire protocol](../udp-wire-protocol.md) reference.

- A change to the packet layout MUST use a new version number.
- Geri MUST accept every version still flashed on a board. Today that's
  versions 1 and 2.
- Geri MUST NOT send ACKs to one sender address more often than
  `ACK_INTERVAL_S`.
- Muninn MUST start recovery by itself when CSI is flowing but no ACK has
  arrived within `RECEIVER_WATCHDOG_ACK_TIMEOUT_S`.

## Consequences

- An ACK is the only thing a receiver trusts, so Geri has to send one only
  when it's really accepting data. Today it ACKs before it knows the sample
  was queued ([#65](https://github.com/dannysauer/grimnir/issues/65)), and
  ACKs aren't authenticated
  ([#92](https://github.com/dannysauer/grimnir/issues/92)).
- Samples aren't acknowledged one by one, so loss is invisible to the sender
  and gaps appear in the data.
- Geri carries a parser for each version until the last old board is
  reflashed.

## Alternatives considered

### Keep version 1

Version 1 worked, but its 16-byte name field truncated the receiver names the
naming convention asks for
([#44](https://github.com/dannysauer/grimnir/issues/44)), and it had no
liveness signal.

### Reboot on a fixed timer or on Wi-Fi state alone

Issue #41 asked for self-recovery from "prolonged reporting stalls". Wi-Fi
state can't see a path that's associated but delivering nothing. An ACK from
Geri tests the whole path.

## Corrections

- 2026-04-25: commit `645d80d` changed the recovery action. The first
  watchdog (commit `8e4515d`) rebooted the board; it now closes and reopens
  the UDP socket. The decision is unchanged.
