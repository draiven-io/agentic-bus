"use client";

import { useState } from "react";
import {
  Users as UsersIcon,
  Plus,
  Trash2,
  Pencil,
  Search,
  ShieldCheck,
  UserCircle,
  X,
} from "lucide-react";

import { AppHeader } from "@/components/app-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useAsync } from "@/hooks/use-async";
import {
  fetchUsers,
  fetchTenants,
  createUser,
  updateUser,
  deleteUser,
} from "@/lib/api";
import type { User, Tenant } from "@/lib/types";

// ── Helpers ──────────────────────────────────────────────────────────

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleString();
}

// ── Create User Dialog ───────────────────────────────────────────────

function CreateUserDialog({
  tenants,
  onCreated,
}: {
  tenants: Tenant[];
  onCreated: () => void;
}) {
  const [subject, setSubject] = useState("");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState("user");
  const [selectedTenantIds, setSelectedTenantIds] = useState<number[]>([]);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function toggleTenant(id: number) {
    setSelectedTenantIds((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id],
    );
  }

  async function handleCreate() {
    setSaving(true);
    setError(null);
    try {
      await createUser({
        subject,
        email,
        display_name: displayName,
        role,
        tenant_ids: selectedTenantIds,
      });
      setSubject("");
      setEmail("");
      setDisplayName("");
      setRole("user");
      setSelectedTenantIds([]);
      setOpen(false);
      onCreated();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="mr-2 h-4 w-4" />
          New User
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Create User</DialogTitle>
          <DialogDescription>
            Add a new user. The subject must match the OIDC{" "}
            <code className="text-xs">sub</code> claim.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="subject">Subject (OIDC sub)</Label>
            <Input
              id="subject"
              placeholder="auth0|abc123"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              placeholder="user@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="displayName">Display Name</Label>
            <Input
              id="displayName"
              placeholder="Jane Doe"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label>Role</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">User</SelectItem>
                <SelectItem value="admin">Admin</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {tenants.length > 0 && (
            <div className="grid gap-2">
              <Label>Tenants</Label>
              <div className="flex flex-wrap gap-2">
                {tenants.map((t) => (
                  <Badge
                    key={t.id}
                    variant={
                      selectedTenantIds.includes(t.id)
                        ? "default"
                        : "outline"
                    }
                    className="cursor-pointer select-none"
                    onClick={() => toggleTenant(t.id)}
                  >
                    {t.name}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button
            onClick={handleCreate}
            disabled={saving || !subject}
          >
            {saving ? "Creating…" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Edit User Dialog ─────────────────────────────────────────────────

function EditUserDialog({
  user,
  tenants,
  onUpdated,
}: {
  user: User;
  tenants: Tenant[];
  onUpdated: () => void;
}) {
  const [email, setEmail] = useState(user.email);
  const [displayName, setDisplayName] = useState(user.display_name);
  const [role, setRole] = useState(user.role);
  const [enabled, setEnabled] = useState(user.enabled);
  const [selectedTenantIds, setSelectedTenantIds] = useState<number[]>(
    user.tenant_ids,
  );
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  function toggleTenant(id: number) {
    setSelectedTenantIds((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id],
    );
  }

  async function handleSave() {
    setSaving(true);
    try {
      await updateUser(user.id, {
        email,
        display_name: displayName,
        role,
        enabled,
        tenant_ids: selectedTenantIds,
      });
      setOpen(false);
      onUpdated();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon">
          <Pencil className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit User: {user.display_name || user.subject}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label>Subject</Label>
            <Input value={user.subject} disabled />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="edit-email">Email</Label>
            <Input
              id="edit-email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="edit-dn">Display Name</Label>
            <Input
              id="edit-dn"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label>Role</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">User</SelectItem>
                <SelectItem value="admin">Admin</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="edit-enabled"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="h-4 w-4"
            />
            <Label htmlFor="edit-enabled">Enabled</Label>
          </div>
          {tenants.length > 0 && (
            <div className="grid gap-2">
              <Label>Tenants</Label>
              <div className="flex flex-wrap gap-2">
                {tenants.map((t) => (
                  <Badge
                    key={t.id}
                    variant={
                      selectedTenantIds.includes(t.id)
                        ? "default"
                        : "outline"
                    }
                    className="cursor-pointer select-none"
                    onClick={() => toggleTenant(t.id)}
                  >
                    {t.name}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Page ─────────────────────────────────────────────────────────────

export default function UsersPage() {
  const [search, setSearch] = useState("");
  const { data: users, loading, error, refetch } = useAsync(fetchUsers, []);
  const { data: tenants } = useAsync(fetchTenants, []);

  const filtered = (users ?? []).filter(
    (u) =>
      u.subject.toLowerCase().includes(search.toLowerCase()) ||
      u.display_name.toLowerCase().includes(search.toLowerCase()) ||
      u.email.toLowerCase().includes(search.toLowerCase()),
  );

  const adminCount = (users ?? []).filter((u) => u.role === "admin").length;
  const userCount = (users ?? []).filter((u) => u.role === "user").length;

  async function handleDelete(userId: number) {
    if (!confirm("Are you sure you want to delete this user?")) return;
    await deleteUser(userId);
    refetch();
  }

  return (
    <>
      <AppHeader breadcrumbs={[{ label: "Users" }]} />
      <div className="flex flex-1 flex-col gap-4 p-4 pt-0">
        {/* Summary cards */}
        <div className="grid auto-rows-min gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                Total Users
              </CardTitle>
              <UsersIcon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {users?.length ?? "—"}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Admins</CardTitle>
              <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{adminCount}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                Regular Users
              </CardTitle>
              <UserCircle className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{userCount}</div>
            </CardContent>
          </Card>
        </div>

        {/* Toolbar */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search users…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
            />
            {search && (
              <button
                className="absolute right-2.5 top-2.5 text-muted-foreground hover:text-foreground"
                onClick={() => setSearch("")}
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          <CreateUserDialog
            tenants={tenants ?? []}
            onCreated={refetch}
          />
        </div>

        {/* Table */}
        <Card>
          <CardContent className="p-0">
            {loading ? (
              <div className="flex items-center justify-center py-12 text-muted-foreground">
                Loading…
              </div>
            ) : error ? (
              <div className="flex items-center justify-center py-12 text-destructive">
                {error}
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Subject</TableHead>
                    <TableHead>Display Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead className="text-center">Role</TableHead>
                    <TableHead className="text-center">Status</TableHead>
                    <TableHead>Tenants</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={8}
                        className="text-center py-8 text-muted-foreground"
                      >
                        No users found.
                      </TableCell>
                    </TableRow>
                  ) : (
                    filtered.map((u) => (
                      <TableRow key={u.id}>
                        <TableCell className="font-mono text-sm max-w-[200px] truncate">
                          {u.subject}
                        </TableCell>
                        <TableCell>{u.display_name || "—"}</TableCell>
                        <TableCell className="text-sm">
                          {u.email || "—"}
                        </TableCell>
                        <TableCell className="text-center">
                          <Badge
                            variant={
                              u.role === "admin"
                                ? "default"
                                : "secondary"
                            }
                          >
                            {u.role}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-center">
                          <Badge
                            variant={u.enabled ? "default" : "destructive"}
                          >
                            {u.enabled ? "Active" : "Disabled"}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {u.tenant_slugs.length > 0
                              ? u.tenant_slugs.map((s) => (
                                  <Badge
                                    key={s}
                                    variant="outline"
                                    className="text-xs"
                                  >
                                    {s}
                                  </Badge>
                                ))
                              : "—"}
                          </div>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {formatDate(u.created_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <EditUserDialog
                              user={u}
                              tenants={tenants ?? []}
                              onUpdated={refetch}
                            />
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleDelete(u.id)}
                            >
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
