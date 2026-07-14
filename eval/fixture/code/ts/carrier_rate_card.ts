/**
 * Carrier rate card lookups for outbound shipment pricing.
 *
 * Each contracted carrier hands us a spreadsheet of prices keyed by
 * weight break and zone, refreshed quarterly and occasionally mid
 * quarter when fuel surcharges move. This module is the boundary that
 * turns those messy spreadsheets into a single lookup call so pricing
 * logic elsewhere never has to know a rate card even exists.
 */

export const FUEL_SURCHARGE_DEFAULT = 0.12;
export const MAX_WEIGHT_KG = 68;
export const RATE_CARD_STALE_AFTER_DAYS = 100;

export class RateCardNotFoundError extends Error {
  constructor(carrier: string, zone: string) {
    super(`no rate card entry for carrier=${carrier} zone=${zone}`);
    this.name = "RateCardNotFoundError";
  }
}

export interface WeightBreak {
  maxKg: number;
  baseCents: number;
}

export interface RateCardEntry {
  carrier: string;
  zone: string;
  weightBreaks: WeightBreak[];
  publishedAt: string; // ISO date
}

function daysSince(isoDate: string, now: Date = new Date()): number {
  const then = new Date(isoDate);
  return (now.getTime() - then.getTime()) / (1000 * 60 * 60 * 24);
}

/**
 * Resolves shipment weight and zone against a carrier's published
 * pricing tiers, and understands that a stale rate card is worse than
 * no rate card -- silently quoting last quarter's diesel price after
 * a surcharge change would undercharge every shipment that week.
 */
export class CarrierRateCard {
  private readonly entries: Map<string, RateCardEntry> = new Map();

  private static key(carrier: string, zone: string): string {
    return `${carrier}::${zone}`;
  }

  loadEntry(entry: RateCardEntry): void {
    this.entries.set(CarrierRateCard.key(entry.carrier, entry.zone), entry);
  }

  loadEntries(entries: RateCardEntry[]): void {
    for (const e of entries) this.loadEntry(e);
  }

  isStale(carrier: string, zone: string): boolean {
    const entry = this.entries.get(CarrierRateCard.key(carrier, zone));
    if (!entry) return true;
    return daysSince(entry.publishedAt) > RATE_CARD_STALE_AFTER_DAYS;
  }

  baseRateForWeight(carrier: string, zone: string, weightKg: number): number {
    const entry = this.entries.get(CarrierRateCard.key(carrier, zone));
    if (!entry) {
      throw new RateCardNotFoundError(carrier, zone);
    }
    if (weightKg > MAX_WEIGHT_KG) {
      throw new Error(`weight ${weightKg}kg exceeds carrier max ${MAX_WEIGHT_KG}kg`);
    }
    const sorted = [...entry.weightBreaks].sort((a, b) => a.maxKg - b.maxKg);
    const matched = sorted.find((wb) => weightKg <= wb.maxKg);
    if (!matched) {
      throw new Error(`no weight break covers ${weightKg}kg for ${carrier}/${zone}`);
    }
    return matched.baseCents;
  }

  quoteWithSurcharge(
    carrier: string,
    zone: string,
    weightKg: number,
    fuelSurcharge: number = FUEL_SURCHARGE_DEFAULT
  ): number {
    const base = this.baseRateForWeight(carrier, zone, weightKg);
    return Math.round(base * (1 + fuelSurcharge));
  }

  cheapestCarrierForZone(
    carriers: string[],
    zone: string,
    weightKg: number
  ): { carrier: string; costCents: number } | null {
    let best: { carrier: string; costCents: number } | null = null;
    for (const carrier of carriers) {
      try {
        const cost = this.quoteWithSurcharge(carrier, zone, weightKg);
        if (!best || cost < best.costCents) {
          best = { carrier, costCents: cost };
        }
      } catch {
        continue; // carrier doesn't service this zone or weight
      }
    }
    return best;
  }
}

export function applyResidentialSurcharge(baseCents: number, isResidential: boolean): number {
  const RESIDENTIAL_SURCHARGE_CENTS = 350;
  return isResidential ? baseCents + RESIDENTIAL_SURCHARGE_CENTS : baseCents;
}

export function centsToDisplayString(cents: number, currency = "USD"): string {
  const major = (cents / 100).toFixed(2);
  return `${currency} ${major}`;
}
