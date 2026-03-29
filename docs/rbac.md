# Role-Based Access Control (RBAC)

Guestbook uses a three-layer permission system: **Site**, **Organization**, and **Event**.

## Permission Layers

| Layer | Scope | Stored On | Purpose |
|-------|-------|-----------|---------|
| **Site** | Entire platform | `User.site_role` | Platform administration and support |
| **Organization** | One org's events | `OrgMembership.org_role` | Event creation and team management |
| **Event** | Single event | `EventManager` | Per-event delegation |

Permission checks cascade: **Site role → Org role → Event role → Deny**.

---

## Site Roles

Stored on `User.site_role`. Every user has exactly one site role.

| Role | Value | Description |
|------|-------|-------------|
| `user` | 1 | Default. Can create orgs, RSVP to events, manage own profile and household. |
| `support` | 2 | Read-only access to all users, orgs, and events. Cannot modify anything outside their own account. For monitoring and customer support. |
| `admin` | 3 | Full platform control. Can manage all users, orgs, events. Can delete anything. |

---

## Organization Roles

Stored on `OrgMembership.org_role`. A user can be a member of multiple orgs with different roles in each.

| Role | Value | Description |
|------|-------|-------------|
| `viewer` | 1 | Read-only access to the org's events and guest lists. For stakeholders who want to monitor. |
| `event_creator` | 2 | Create events within the org. Edit, delete, and assign event managers for their own events only. |
| `admin` | 3 | Create, edit, and delete any event in the org. Manage org members. Assign event managers for any event. |
| `owner` | 4 | Full org control. All admin permissions plus: delete the org, change other members' roles including promoting to admin, transfer ownership. |

---

## Event Roles

Stored on `EventManager` (user_id + event_id link table). Assigned by org admins/owners or the event creator.

| Role | Description |
|------|-------------|
| `event_manager` | Edit the event, view guest list, export CSV, generate QR codes. Cannot delete the event or assign other managers. |

---

## Permission Matrix

| Action | Site Admin | Site Support | Org Owner | Org Admin | Org Event Creator | Org Viewer | Event Manager | User/Guest |
|--------|:---------:|:----------:|:---------:|:---------:|:-----------------:|:----------:|:-------------:|:----------:|
| **Platform** | | | | | | | | |
| Manage all users | x | | | | | | | |
| View all users | x | x | | | | | | |
| Manage all orgs | x | | | | | | | |
| View all events (any org) | x | x | | | | | | |
| Delete any event | x | | | | | | | |
| **Organization** | | | | | | | | |
| Create an organization | x | | x* | x* | x* | x* | x* | x* |
| Edit org settings | x | | x | x | | | | |
| Delete organization | x | | x | | | | | |
| Invite/remove org members | x | | x | x | | | | |
| Change org member roles | x | | x | | | | | |
| **Events** | | | | | | | | |
| Create events in org | x | | x | x | x | | | |
| Edit events | x | | x | x | own | | assigned | |
| Delete events | x | | x | x | own | | | |
| View guest lists | x | x | x | x | own | x | assigned | |
| Export CSV | x | | x | x | own | x | assigned | |
| Generate QR codes | x | | x | x | own | x | assigned | |
| Assign event managers | x | | x | x | own | | | |
| Archive/unarchive events | x | | x | x | own | | assigned | |
| **Guests** | | | | | | | | |
| View public events | x | x | x | x | x | x | x | x |
| Access private events | x | x | org members | org members | org members | org members | assigned | invite code |
| RSVP to events | x | x | x | x | x | x | x | x |
| Edit own RSVP | x | x | x | x | x | x | x | x |

*\* Any authenticated user can create a new organization (they become the owner).*

---

## Event Visibility

Organizers choose visibility when creating/editing an event.

| Setting | Landing page (`/`) | Direct link (`/e/{code}`) |
|---------|--------------------|--------------------------|
| **Public** | Listed for everyone | Open to everyone |
| **Private** | Not listed | Anyone with the invite code can access |

Org members and event managers can always see their org's events regardless of visibility setting.

---

## Data Model

```
User
├── site_role: user | support | admin
├── household_id → Household (optional)
├── food_preference, dietary_restrictions, alcohol
└── has many: OrgMembership, EventManager, RSVP

Organization
├── name, slug
└── has many: OrgMembership, Event

OrgMembership
├── user_id → User
├── org_id → Organization
└── org_role: viewer | event_creator | admin | owner

Event
├── org_id → Organization
├── visibility: public | private
├── invite_code (for sharing)
└── has many: EventManager, RSVP

EventManager
├── user_id → User
└── event_id → Event

Household
├── name, invite_code (for joining)
└── has many: HouseholdMember

HouseholdMember
├── household_id → Household
├── user_id → User (optional, for linked accounts)
└── name, food_preference, dietary_restrictions, alcohol
```

---

## Permission Check Order

When a request comes in, permissions are resolved in this order:

1. **Is the user a site admin?** → Allow everything
2. **Is the user site support?** → Allow read-only access to everything
3. **Is the action org-scoped?** → Check `OrgMembership.org_role` for the relevant org
4. **Is the action event-scoped?** → Check org role first, then `EventManager` assignment
5. **None of the above?** → Deny (403)

For event access specifically:
```
site_admin?           → full access
site_support?         → read-only
org owner/admin?      → full access to org's events
org event_creator?    → full access to own events, read to others
org viewer?           → read-only to org's events
event_manager?        → edit access to assigned event only
has invite code?      → guest access (RSVP)
public event?         → guest access (RSVP)
otherwise             → deny
```

---

## Household System

Households are separate from the RBAC system. They exist to simplify RSVPs.

- Any user can **create** a household (they become a member automatically)
- Other users **join** via an invite code
- Household members can be **linked** (has a user account) or **unlinked** (just a name, e.g. children)
- When RSVPing, users select from: themselves + household members + ad-hoc extra guests
- Each user belongs to at most one household
- All household members can manage the member list

---

## CLI Quick Reference

```bash
# Create a site admin
guestbook create-admin --email admin@example.com

# The admin can then:
# - Manage users at /admin/users
# - View all orgs at /admin
# - Create orgs or promote users via the web UI

# Regular users:
# - Create orgs at /orgs/new
# - Manage their org at /orgs/{slug}
# - Create events within their org
```
