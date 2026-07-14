/**
 * Delivery window negotiation for the last-mile scheduling service.
 *
 * Customers pick a two-hour slot at checkout, but the courier fleet
 * has finite capacity per slot per depot. This module exists because
 * naively accepting every requested slot leads to a depot promising
 * three hundred deliveries between 2pm and 4pm with forty vans on the
 * road -- the math has to be rejected before it becomes a promise.
 */

export const SLOT_DURATION_MINUTES = 120;
export const MAX_SLOTS_PER_DAY = 7;
export const DEFAULT_VAN_CAPACITY_PER_SLOT = 18;

export class SlotCapacityExceededError extends Error {
  constructor(depotId: string, slotStart: string) {
    super(`no capacity remaining in slot ${slotStart} at depot ${depotId}`);
    this.name = "SlotCapacityExceededError";
  }
}

export interface DeliveryWindow {
  depotId: string;
  slotStart: string; // ISO 8601
  slotEndMinutes: number;
  bookedCount: number;
  capacity: number;
}

export function slotStartsForDay(dayStartIso: string): string[] {
  const base = new Date(dayStartIso);
  const starts: string[] = [];
  for (let i = 0; i < MAX_SLOTS_PER_DAY; i++) {
    const slot = new Date(base.getTime() + i * SLOT_DURATION_MINUTES * 60_000);
    starts.push(slot.toISOString());
  }
  return starts;
}

function minutesBetween(a: Date, b: Date): number {
  return Math.abs(a.getTime() - b.getTime()) / 60_000;
}

/**
 * Tracks how full each delivery slot is for a single depot and enforces
 * that the fleet never gets oversold for a given afternoon.
 */
export class DepotSlotBook {
  private readonly depotId: string;
  private readonly slots: Map<string, DeliveryWindow> = new Map();

  constructor(depotId: string, vanCapacityPerSlot: number = DEFAULT_VAN_CAPACITY_PER_SLOT) {
    this.depotId = depotId;
    for (const slotStart of slotStartsForDay(new Date().toISOString())) {
      this.slots.set(slotStart, {
        depotId,
        slotStart,
        slotEndMinutes: SLOT_DURATION_MINUTES,
        bookedCount: 0,
        capacity: vanCapacityPerSlot,
      });
    }
  }

  reserveSlot(slotStart: string): DeliveryWindow {
    const window = this.slots.get(slotStart);
    if (!window) {
      throw new Error(`unknown slot ${slotStart} for depot ${this.depotId}`);
    }
    if (window.bookedCount >= window.capacity) {
      throw new SlotCapacityExceededError(this.depotId, slotStart);
    }
    window.bookedCount += 1;
    return window;
  }

  releaseSlot(slotStart: string): void {
    const window = this.slots.get(slotStart);
    if (window && window.bookedCount > 0) {
      window.bookedCount -= 1;
    }
  }

  utilizationRatio(slotStart: string): number {
    const window = this.slots.get(slotStart);
    if (!window) return 0;
    return window.bookedCount / window.capacity;
  }

  /**
   * Surfaces the slots most likely to sell out soon, so the app can
   * nudge customers toward less popular windows instead of letting
   * everyone pile into the same 5-7pm slot.
   */
  nearCapacitySlots(threshold: number = 0.85): DeliveryWindow[] {
    return Array.from(this.slots.values()).filter(
      (w) => w.bookedCount / w.capacity >= threshold
    );
  }

  totalBooked(): number {
    let sum = 0;
    for (const w of this.slots.values()) sum += w.bookedCount;
    return sum;
  }
}

export function chooseFallbackSlot(
  book: DepotSlotBook,
  preferredSlot: string,
  allSlots: string[]
): string {
  try {
    book.reserveSlot(preferredSlot);
    return preferredSlot;
  } catch (err) {
    if (!(err instanceof SlotCapacityExceededError)) throw err;
  }
  for (const candidate of allSlots) {
    if (candidate === preferredSlot) continue;
    try {
      book.reserveSlot(candidate);
      return candidate;
    } catch {
      continue;
    }
  }
  throw new Error("every slot for the day is fully booked");
}

export function estimateVansNeeded(
  bookedCount: number,
  parcelsPerVanRun: number
): number {
  return Math.ceil(bookedCount / Math.max(parcelsPerVanRun, 1));
}
