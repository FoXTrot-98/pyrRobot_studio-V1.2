interface SwitchProps {
  on: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}

export function Switch({ on, onChange, disabled }: SwitchProps) {
  return (
    <div
      className={`switch${on ? " on" : ""}${disabled ? " disabled" : ""}`}
      onClick={() => !disabled && onChange(!on)}
      role="switch"
      aria-checked={on}
    >
      <div className="switch-knob" />
    </div>
  );
}
