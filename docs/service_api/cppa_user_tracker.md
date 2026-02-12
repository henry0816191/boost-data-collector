# cppa_user_tracker.services

**Module path:** `cppa_user_tracker.services`
**Description:** Identity, profiles (GitHubAccount, SlackUser, MailingListProfile, etc.), emails, and staging (TmpIdentity, TempProfileIdentityRelation). Single place for all writes to cppa_user_tracker models.

**Type notation:** Model types refer to `cppa_user_tracker.models` (e.g. `Identity`, `BaseProfile`, `Email`).

---

## Identity

| Function                 | Parameter types                                                                    | Return type             | Description                                                                             |
| ------------------------ | ---------------------------------------------------------------------------------- | ----------------------- | --------------------------------------------------------------------------------------- |
| `create_identity`        | `display_name: str = ""`, `description: str = ""`                                  | `Identity`              | Create a new Identity.                                                                  |
| `get_or_create_identity` | `display_name: str = ""`, `description: str = ""`, `defaults: dict \| None = None` | `tuple[Identity, bool]` | Get or create an Identity by `display_name`. `defaults` overrides fields when creating. |

---

## TmpIdentity

| Function              | Parameter types                                   | Return type   | Description                     |
| --------------------- | ------------------------------------------------- | ------------- | ------------------------------- |
| `create_tmp_identity` | `display_name: str = ""`, `description: str = ""` | `TmpIdentity` | Create a TmpIdentity (staging). |

---

## TempProfileIdentityRelation

| Function                                | Parameter types                                             | Return type                                | Description                                    |
| --------------------------------------- | ----------------------------------------------------------- | ------------------------------------------ | ---------------------------------------------- |
| `add_temp_profile_identity_relation`    | `base_profile: BaseProfile`, `target_identity: TmpIdentity` | `tuple[TempProfileIdentityRelation, bool]` | Link a BaseProfile to a TmpIdentity (staging). |
| `remove_temp_profile_identity_relation` | `base_profile: BaseProfile`, `target_identity: TmpIdentity` | `None`                                     | Remove the staging relation.                   |

---

## MailingListProfile

| Function                             | Parameter types                             | Return type                       | Description                                                                                                                                                                                                                                                                                                                       |
| ------------------------------------ | ------------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `get_or_create_mailing_list_profile` | `display_name: str = ""`, `email: str = ""` | `tuple[MailingListProfile, bool]` | Get or create a MailingListProfile by display_name and email. Looks up a profile with this display_name and an Email with this address; if found, returns it. Otherwise creates a new profile, adds the email via `add_email`, and returns the new profile. Raises `ValueError` if `display_name` or `email` is missing or empty. |

---

## Email

| Function       | Parameter types                                                                                 | Return type | Description                                                        |
| -------------- | ----------------------------------------------------------------------------------------------- | ----------- | ------------------------------------------------------------------ |
| `add_email`    | `base_profile: BaseProfile`, `email: str`, `is_primary: bool = False`, `is_active: bool = True` | `Email`     | Add an email to a BaseProfile.                                     |
| `update_email` | `email_obj: Email`, `**kwargs: Any`                                                             | `Email`     | Update an Email. Allowed keys: `email`, `is_primary`, `is_active`. |
| `remove_email` | `email_obj: Email`                                                                              | `None`      | Delete an email.                                                   |

---

## Related

- [Service API index](README.md)
- [Contributing](../Contributing.md)
- [Schema](../Schema.md)
