/**
 * Fixed UTC+7 (WIB) arithmetic — no `Intl`, no host time zone.
 *
 * The engine must produce the same answer in a browser in Jakarta, in a CI
 * container on UTC and in Node on a laptop. Every calendar operation here is
 * integer arithmetic on the epoch day count, so the host configuration cannot
 * influence the result.
 */
import { SECONDS_PER_DAY, WIB_OFFSET_S } from "./types";

export interface CivilDate {
  readonly year: number;
  /** 1-12, never 0-based */
  readonly month: number;
  readonly day: number;
}

export interface WibDateTime {
  readonly date: CivilDate;
  /** seconds since WIB midnight; fractional when the instant has milliseconds */
  readonly secondsOfDay: number;
}

const MS_PER_DAY = SECONDS_PER_DAY * 1000;
const WIB_OFFSET_MS = WIB_OFFSET_S * 1000;

/**
 * Days since 1970-01-01 -> civil date (Howard Hinnant's `civil_from_days`).
 * Valid for the whole range the schedule can occupy.
 */
export function civilFromDays(days: number): CivilDate {
  const z = days + 719_468;
  const era = Math.floor(z / 146_097);
  const dayOfEra = z - era * 146_097; // [0, 146096]
  const yearOfEra = Math.floor(
    (dayOfEra - Math.floor(dayOfEra / 1460) + Math.floor(dayOfEra / 36_524) - Math.floor(dayOfEra / 146_096)) / 365,
  );
  const year = yearOfEra + era * 400;
  const dayOfYear = dayOfEra - (365 * yearOfEra + Math.floor(yearOfEra / 4) - Math.floor(yearOfEra / 100));
  const mp = Math.floor((5 * dayOfYear + 2) / 153); // [0, 11]
  const day = dayOfYear - Math.floor((153 * mp + 2) / 5) + 1;
  const month = mp < 10 ? mp + 3 : mp - 9;
  return { year: month <= 2 ? year + 1 : year, month, day };
}

/** Civil date -> days since 1970-01-01 (`days_from_civil`). */
export function daysFromCivil(date: CivilDate): number {
  const year = date.month <= 2 ? date.year - 1 : date.year;
  const era = Math.floor(year / 400);
  const yearOfEra = year - era * 400; // [0, 399]
  const monthIndex = date.month > 2 ? date.month - 3 : date.month + 9;
  const dayOfYear = Math.floor((153 * monthIndex + 2) / 5) + date.day - 1;
  const dayOfEra =
    yearOfEra * 365 + Math.floor(yearOfEra / 4) - Math.floor(yearOfEra / 100) + dayOfYear;
  return era * 146_097 + dayOfEra - 719_468;
}

/** Split an epoch instant into the WIB civil date and seconds since its midnight. */
export function wibFromEpochMs(epochMs: number): WibDateTime {
  const shifted = epochMs + WIB_OFFSET_MS;
  const dayIndex = Math.floor(shifted / MS_PER_DAY);
  const millisIntoDay = shifted - dayIndex * MS_PER_DAY;
  return {
    date: civilFromDays(dayIndex),
    secondsOfDay: millisIntoDay / 1000,
  };
}

/** WIB midnight of a civil date, as epoch milliseconds. */
export function midnightEpochMs(date: CivilDate): number {
  return daysFromCivil(date) * MS_PER_DAY - WIB_OFFSET_MS;
}

/** Epoch milliseconds for a WIB civil date plus seconds since its midnight. */
export function wibToEpochMs(date: CivilDate, secondsOfDay: number): number {
  return midnightEpochMs(date) + Math.round(secondsOfDay * 1000);
}

/** Shift a civil date by whole days (negative for earlier). */
export function addDays(date: CivilDate, delta: number): CivilDate {
  return civilFromDays(daysFromCivil(date) + delta);
}

/** ISO `YYYY-MM-DD`, the form the manifest uses for `effective_from`. */
export function isoDate(date: CivilDate): string {
  const month = String(date.month).padStart(2, "0");
  const day = String(date.day).padStart(2, "0");
  return `${String(date.year).padStart(4, "0")}-${month}-${day}`;
}

/** Parse `YYYY-MM-DD`; throws on anything else rather than guessing. */
export function parseIsoDate(value: string): CivilDate {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) throw new Error(`not an ISO date: ${value}`);
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
}

/** Compare two civil dates: negative when `a` is earlier. */
export function compareDates(a: CivilDate, b: CivilDate): number {
  return daysFromCivil(a) - daysFromCivil(b);
}

/** `HH:MM:SS`, truncating a fractional second (the Gapeka prints whole seconds). */
export function formatSod(secondsOfDay: number): string {
  const whole = Math.trunc(secondsOfDay);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const seconds = whole % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(
    seconds,
  ).padStart(2, "0")}`;
}

/** `HH:MM`, for the status pill. */
export function formatSodHm(secondsOfDay: number): string {
  const whole = Math.trunc(secondsOfDay);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}
