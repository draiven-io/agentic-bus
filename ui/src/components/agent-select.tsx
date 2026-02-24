"use client";

import * as React from "react";
import { useState, useEffect, useMemo } from "react";
import { Check, ChevronsUpDown, Bot, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  fetchPersistentAgents,
  fetchManagedAgents,
  fetchEphemeralAgents,
} from "@/lib/api";
import type {
  PersistentAgent,
  ManagedAgent,
  EphemeralAgent,
} from "@/lib/types";

interface AgentOption {
  agent_id: string;
  label: string;
  group: "persistent" | "managed" | "ephemeral";
}

interface AgentSelectProps {
  /** Currently selected agent ID (empty string or undefined = none) */
  value?: string;
  /** Callback when selection changes */
  onChange: (agentId: string) => void;
  /** Placeholder text when nothing is selected */
  placeholder?: string;
}

export function AgentSelect({
  value,
  onChange,
  placeholder = "Select validator agent…",
}: AgentSelectProps) {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const [persistent, managed, ephemeral] = await Promise.allSettled([
          fetchPersistentAgents(),
          fetchManagedAgents(),
          fetchEphemeralAgents(),
        ]);

        if (cancelled) return;

        const options: AgentOption[] = [];

        if (persistent.status === "fulfilled") {
          persistent.value.forEach((a: PersistentAgent) =>
            options.push({
              agent_id: a.agent_id,
              label: `${a.agent_id} (${a.status})`,
              group: "persistent",
            }),
          );
        }

        if (managed.status === "fulfilled") {
          managed.value.forEach((a: ManagedAgent) =>
            options.push({
              agent_id: a.agent_id,
              label: `${a.agent_id} — ${a.name}`,
              group: "managed",
            }),
          );
        }

        if (ephemeral.status === "fulfilled") {
          ephemeral.value.forEach((a: EphemeralAgent) =>
            options.push({
              agent_id: a.agent_id,
              label: `${a.agent_id} (ephemeral)`,
              group: "ephemeral",
            }),
          );
        }

        // Deduplicate by agent_id
        const seen = new Set<string>();
        const deduped = options.filter((o) => {
          if (seen.has(o.agent_id)) return false;
          seen.add(o.agent_id);
          return true;
        });

        setAgents(deduped);
      } catch {
        // Silently fail – we'll show empty list
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const grouped = useMemo(() => {
    const groups: Record<string, AgentOption[]> = {};
    for (const a of agents) {
      (groups[a.group] ??= []).push(a);
    }
    return groups;
  }, [agents]);

  const groupLabels: Record<string, string> = {
    persistent: "Persistent Agents",
    managed: "Managed Agents",
    ephemeral: "Ephemeral Agents",
  };

  const selectedLabel = agents.find((a) => a.agent_id === value)?.label;

  return (
    <div className="grid gap-1.5">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="h-9 w-full justify-between font-normal text-xs border-zinc-700 bg-zinc-900/50"
          >
            {value ? (
              <span className="flex items-center gap-1.5 truncate">
                <Bot className="size-3 shrink-0 text-violet-400" />
                <span className="truncate">{selectedLabel ?? value}</span>
              </span>
            ) : (
              <span className="text-muted-foreground">{placeholder}</span>
            )}
            <ChevronsUpDown className="ml-2 h-3.5 w-3.5 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
          <Command>
            <CommandInput placeholder="Search agents…" />
            <CommandList>
              {loading ? (
                <div className="py-6 text-center text-sm text-muted-foreground">
                  Loading agents…
                </div>
              ) : agents.length === 0 ? (
                <CommandEmpty>No agents found.</CommandEmpty>
              ) : (
                <>
                  {/* "None" option to clear selection */}
                  <CommandGroup heading="Options">
                    <CommandItem
                      value="__none__"
                      onSelect={() => {
                        onChange("");
                        setOpen(false);
                      }}
                    >
                      <Check
                        className={cn(
                          "mr-2 h-4 w-4",
                          !value ? "opacity-100" : "opacity-0",
                        )}
                      />
                      <span className="text-muted-foreground italic">
                        No validator (skip validation)
                      </span>
                    </CommandItem>
                  </CommandGroup>

                  {Object.entries(grouped).map(([group, items]) => (
                    <CommandGroup key={group} heading={groupLabels[group] ?? group}>
                      {items.map((agent) => {
                        const isSelected = value === agent.agent_id;
                        return (
                          <CommandItem
                            key={agent.agent_id}
                            value={agent.agent_id}
                            onSelect={() => {
                              onChange(agent.agent_id);
                              setOpen(false);
                            }}
                          >
                            <Check
                              className={cn(
                                "mr-2 h-4 w-4",
                                isSelected ? "opacity-100" : "opacity-0",
                              )}
                            />
                            <span className="truncate">{agent.label}</span>
                          </CommandItem>
                        );
                      })}
                    </CommandGroup>
                  ))}
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {/* Clear button when an agent is selected */}
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          className="flex items-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors self-start"
        >
          <X className="size-3" />
          Clear validator
        </button>
      )}
    </div>
  );
}
