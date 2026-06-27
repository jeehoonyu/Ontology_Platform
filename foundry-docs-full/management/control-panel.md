<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · MANAGEMENT & ENABLEMENT</b><br>
<span style="font-size:22px"><b>Control Panel</b></span><br>
<span style="color:#ABB3BF">Foundry's unified, self-service interface for administering the platform — organizations, users & groups, roles, authentication, tokens, and resource usage.</span>
</td></tr></table>

## What it is

Control Panel is where platform administrators govern Foundry from one place. It manages the **security hierarchy** (enrollment → organizations → spaces → groups → users), grants **roles** that map to capabilities, configures **authentication** (identity providers), issues and governs **API tokens / service accounts / OAuth clients**, and tracks **resource & usage** with quotas. It is the administrative backbone the rest of the platform's access control depends on.

## How it works

1. **Enrollment & organizations.** An *enrollment* is one instance of Foundry and contains one or more *organizations*; organizations contain *spaces*. These form the scope hierarchy for access control.
2. **Users & groups.** Administrators create users (assigning organization and marking access, and an active/inactive status) and groups; group memberships can carry an **expiration** and management permissions (*manage permissions*, *manage membership*).
3. **Roles → capabilities.** A role granted at a scope (enrollment/organization/space/project) confers a set of capabilities (`view → edit → manage → administer`). Grants **inherit downward** (an org grant applies to its spaces) and resolve through **group membership** (non-expired only).
4. **Access decision.** For a (user, scope, capability) query, the platform unions the user's direct grants and group grants across the scope and its ancestors, maps them to capabilities, and allows or denies — denying outright if the user is inactive.
5. **Authentication.** Identity providers (SAML/OIDC) map IdP assertion attributes to Foundry user attributes (username, email, groups). Multiple providers can be onboarded.
6. **Tokens.** API tokens (and service-account / OAuth clients) carry scopes and optional expiry; a token is **invalid while its owning user account is inactive**, and can be revoked.
7. **Resource & usage.** Usage is recorded per account/project/resource and metric; quotas bound consumption and are checked against accumulated usage.

## User interface

The Control Panel opens from the workspace sidebar as a tabbed admin console.

<table>
<tr style="background:#1C2127;color:#fff"><th align="left" style="border:1px solid #383E47;padding:6px 10px">Tab</th><th align="left" style="border:1px solid #383E47;padding:6px 10px">Manages</th></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Organizations</span></td><td style="border:1px solid #383E47;padding:6px 10px">Enrollment, organizations, spaces</td></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Users / Groups</span></td><td style="border:1px solid #383E47;padding:6px 10px">Accounts, memberships, status, marking access</td></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Roles</span></td><td style="border:1px solid #383E47;padding:6px 10px">Scope-level role grants to users/groups</td></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Authentication</span></td><td style="border:1px solid #383E47;padding:6px 10px">Identity providers, attribute mapping</td></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Tokens / Apps</span></td><td style="border:1px solid #383E47;padding:6px 10px">API tokens, service accounts, OAuth clients</td></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Resources</span></td><td style="border:1px solid #383E47;padding:6px 10px">Usage metrics, quotas, spend</td></tr>
</table>

Status chips: <span style="color:#238551"><b>● active</b></span> · <span style="color:#CD4246"><b>● inactive / revoked</b></span> · <span style="color:#C87619"><b>● expiring membership</b></span> · <span style="color:#2D72D2"><b>● grant role</b></span>.

## Worked example

Grant the *Engineers* group the `editor` role at the enrollment scope; user **alice** (an active member) is then allowed to `edit` in any space under that enrollment by inheritance, while **bob** — whose membership expired — is denied. Deactivating alice immediately invalidates all her API tokens until she logs in again.

## How it connects to the rest of Foundry

- **Security & governance** — roles/markings here gate every resource; pairs with [markings](../security/markings-and-classification.md).
- **Developer toolchain** — tokens/OAuth clients authenticate the [Platform APIs & OSDK](../dev-toolchain/platform-apis-and-sdks.md).
- **Observability** — usage metrics feed resource monitoring.

## In this platform (local equivalent)

`admin_directory.py` (`/admin/enrollments|organizations|spaces|users|groups|roles/grant`, `/admin/access-check`) · `admin_auth.py` (`/admin/auth-providers`, `/admin/tokens(/validate)`, `/admin/service-accounts`, `/admin/oauth-clients`) · `admin_usage.py` (`/admin/usage/*`). Verified by `oms/test_admin.py` (40 assertions).

## Official documentation
- [Administration: Overview](https://www.palantir.com/docs/foundry/administration/overview)
- [Management: Manage users](https://www.palantir.com/docs/foundry/platform-security-management/manage-users)
- [Management: Manage groups](https://www.palantir.com/docs/foundry/platform-security-management/manage-groups)
- [Management: Manage organizations and spaces](https://www.palantir.com/docs/foundry/platform-security-management/manage-orgs-and-spaces)
- [Authentication: Overview](https://www.palantir.com/docs/foundry/authentication/overview)
