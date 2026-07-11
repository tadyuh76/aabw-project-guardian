import { Clock } from "@phosphor-icons/react";

type TimeRangeOption<Value extends string> = {
  value: Value;
  label: string;
};

export function TimeRangeSelect<Value extends string>({
  ariaLabel,
  value,
  options,
  onChange,
}: {
  ariaLabel: string;
  value: Value;
  options: readonly TimeRangeOption<Value>[];
  onChange: (value: Value) => void;
}) {
  return (
    <label className="time-range-filter">
      <Clock size={14} aria-hidden="true" />
      <span className="sr-only">{ariaLabel}</span>
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange(event.target.value as Value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  );
}
