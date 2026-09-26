import React, { useState, useRef, useEffect } from "react";
import { ChevronDown, ChevronUp, Check } from "lucide-react";

export type BadgeVariant = "blue" | "emerald" | "amber" | "gray" | "purple" | "rose";

export interface CustomSelectOption<T extends string | number | null = string | number | null> {
  value: T;
  label: string;
  sublabel?: string;
  badge?: string;
  badgeVariant?: BadgeVariant;
  icon?: React.ReactNode;
  disabled?: boolean;
}

export interface CustomSelectProps<T extends string | number | null = string | number | null> {
  value: T;
  options: CustomSelectOption<T>[];
  onChange: (value: T) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  triggerClassName?: string;
  menuClassName?: string;
  size?: "sm" | "md";
  id?: string;
  ariaLabel?: string;
  direction?: "auto" | "up" | "down";
  align?: "left" | "right";
}

const BADGE_STYLES: Record<BadgeVariant, string> = {
  blue: "text-blue-400 bg-blue-950/60 border-blue-800/50",
  emerald: "text-emerald-400 bg-emerald-950/60 border-emerald-800/50",
  amber: "text-amber-400 bg-amber-950/60 border-amber-800/50",
  gray: "text-gray-400 bg-gray-800/80 border-gray-700/60",
  purple: "text-purple-400 bg-purple-950/60 border-purple-800/50",
  rose: "text-rose-400 bg-rose-950/60 border-rose-800/50",
};

export function CustomSelect<T extends string | number | null = string | number | null>({
  value,
  options,
  onChange,
  placeholder = "-- 请选择 --",
  disabled = false,
  className = "",
  triggerClassName = "",
  menuClassName = "",
  size = "md",
  id,
  ariaLabel,
  direction = "auto",
  align = "left",
}: CustomSelectProps<T>) {
  const [isOpen, setIsOpen] = useState(false);
  const [openUpward, setOpenUpward] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Determine open direction based on viewport bounds
  useEffect(() => {
    if (!isOpen || !containerRef.current) return;
    if (direction === "up") {
      setOpenUpward(true);
      return;
    }
    if (direction === "down") {
      setOpenUpward(false);
      return;
    }

    const rect = containerRef.current.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;
    if (spaceBelow < 220 && spaceAbove > 180) {
      setOpenUpward(true);
    } else {
      setOpenUpward(false);
    }
  }, [isOpen, direction]);

  // Close on outside click or Escape key
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const selectedOption = options.find((opt) => opt.value === value);

  const pyPadding = size === "sm" ? "py-1.5 px-2.5 text-xs" : "py-2 px-3 text-xs";

  return (
    <div className={`relative ${className}`} ref={containerRef}>
      {/* Hidden native select for form accessibility and test compatibility */}
      {id && (
        <select
          id={id}
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(e) => {
            const rawVal = e.target.value;
            const match = options.find(
              (o) => (o.value === null || o.value === undefined ? "" : String(o.value)) === rawVal
            );
            if (match) {
              onChange(match.value);
            } else if (rawVal === "") {
              onChange(null as T);
            }
          }}
          disabled={disabled}
          tabIndex={-1}
          aria-hidden="true"
          className="sr-only"
        >
          {options.map((opt, i) => (
            <option
              key={`${String(opt.value)}-${i}`}
              value={opt.value === null || opt.value === undefined ? "" : String(opt.value)}
              disabled={opt.disabled}
            >
              {opt.label}
            </option>
          ))}
        </select>
      )}

      {/* Trigger Button */}
      <button
        type="button"
        id={id ? `${id}-trigger` : undefined}
        aria-label={ariaLabel || selectedOption?.label || placeholder}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        disabled={disabled}
        onClick={() => !disabled && setIsOpen(!isOpen)}
        className={`w-full input flex items-center justify-between text-left transition select-none ${
          disabled
            ? "opacity-60 cursor-not-allowed bg-surface-2/40"
            : "cursor-pointer hover:border-gray-600 focus:border-blue-500"
        } ${pyPadding} ${triggerClassName}`}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
          {selectedOption?.icon && (
            <span className="shrink-0 flex items-center">{selectedOption.icon}</span>
          )}
          {selectedOption ? (
            <div className="min-w-0 flex-1 truncate">
              <span className="text-gray-200 font-medium">{selectedOption.label}</span>
              {selectedOption.sublabel && (
                <span className="text-gray-400 font-normal ml-1.5 text-[11px] truncate">
                  {selectedOption.sublabel}
                </span>
              )}
            </div>
          ) : (
            <span className="text-gray-400 truncate">{placeholder}</span>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0 ml-1">
          {selectedOption?.badge && (
            <span
              className={`text-[10px] font-medium border rounded px-1.5 py-0.5 whitespace-nowrap ${
                BADGE_STYLES[selectedOption.badgeVariant || "gray"]
              }`}
            >
              {selectedOption.badge}
            </span>
          )}
          {isOpen ? (
            <ChevronUp className="h-4 w-4 text-gray-400 shrink-0 transition-transform" />
          ) : (
            <ChevronDown className="h-4 w-4 text-gray-400 shrink-0 transition-transform" />
          )}
        </div>
      </button>

      {/* Dropdown Menu */}
      {isOpen && !disabled && (
        <div
          role="listbox"
          className={`absolute ${align === "right" ? "right-0" : "left-0"} ${
            openUpward ? "bottom-full mb-1.5" : "top-full mt-1.5"
          } z-50 bg-gray-900 border border-gray-700 rounded-lg shadow-2xl p-1 min-w-full w-max max-w-[calc(100vw-32px)] sm:max-w-md max-h-60 overflow-y-auto space-y-0.5 ${menuClassName}`}
        >
          {options.length === 0 ? (
            <div className="p-3 text-center text-xs text-gray-500">暂无可用选项</div>
          ) : (
            options.map((opt, idx) => {
              const isSelected = opt.value === value;
              return (
                <div
                  key={`${String(opt.value)}-${idx}`}
                  role="option"
                  aria-selected={isSelected}
                  aria-disabled={opt.disabled}
                  onClick={() => {
                    if (opt.disabled) return;
                    onChange(opt.value);
                    setIsOpen(false);
                  }}
                  className={`px-2.5 py-1.5 rounded cursor-pointer flex items-center justify-between gap-2 transition ${
                    opt.disabled
                      ? "opacity-40 cursor-not-allowed text-gray-500"
                      : isSelected
                      ? "bg-blue-950/70 border border-blue-800/60 text-white font-medium"
                      : "hover:bg-gray-800 text-gray-300"
                  }`}
                >
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    {opt.icon && <span className="shrink-0 flex items-center">{opt.icon}</span>}
                    <div className="min-w-0 flex-1 truncate">
                      <span className="text-xs">{opt.label}</span>
                      {opt.sublabel && (
                        <span className="text-gray-400 font-normal text-[11px] ml-1.5 truncate">
                          {opt.sublabel}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0 ml-2">
                    {opt.badge && (
                      <span
                        className={`text-[10px] font-medium border rounded px-1.5 py-0.5 ${
                          BADGE_STYLES[opt.badgeVariant || "gray"]
                        }`}
                      >
                        {opt.badge}
                      </span>
                    )}
                    {isSelected && <Check className="h-3.5 w-3.5 text-blue-400 shrink-0" />}
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
