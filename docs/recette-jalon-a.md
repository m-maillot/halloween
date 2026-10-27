# Recette du jalon A (moteur complet, pilotable en ligne de commande et par l'API)

Référence : [spec 1 §11](spec-1-moteur.md). Chaque critère est rattaché aux tests automatiques qui le démontrent (matériel simulé : broches fictives, faux Home Assistant, temps virtuel) et à l'essai réel sur le Pi qui reste à faire. Un test (`engine/tests/test_recette_traceability.py`) vérifie que chaque test cité ici existe.

Légende : ✅ démontré automatiquement · ⏳ à valider sur le matériel (non fait).

Les tests de bout en bout, un par critère, sont dans [`test_acceptance_jalon_a.py`](../engine/tests/test_acceptance_jalon_a.py) (notés **C1**… ci-dessous) ; les autres tests sont ciblés.

## Résultat

| # | Critère (résumé) | Automatique | Essai réel |
|---|---|---|---|
| 1 | 4 relais + bouton créés par l'API, nom + image, testables | ✅ | ⏳ [test-materiel §3-5](test-materiel.md) |
| 2 | `latched` maintenu, `push` : impulsion et 2e `trigger` ignoré | ✅ | ⏳ [test-materiel §4, §6](test-materiel.md) |
| 3 | Corps JSON Home Assistant limité aux paramètres autorisés | ✅ | ⏳ [test-home-assistant §3-4](test-home-assistant.md) |
| 4 | `parallel` : relais et lumière simultanés | ✅ | ⏳ [test-materiel §7](test-materiel.md) |
| 5 | Appui court lance, appui long arrête et remet au repos en < 1 s | ✅ | ⏳ [test-materiel §5, §8](test-materiel.md) |
| 6 | Coupure de Home Assistant en plein run | ✅ | ⏳ [test-home-assistant §4-5](test-home-assistant.md) |
| 7 | Redémarrage du Pi : relais OFF, config et déclencheurs rechargés | ✅ | ⏳ [test-materiel §8, §10](test-materiel.md) |
| 8 | Programme ou config invalide rejeté avec erreur localisée | ✅ | n/a |
| 9 | Suite entièrement exécutable sans matériel | ✅ | n/a |
| 10 | Verrouillage (423, code, STOP libre, déclencheurs actifs, délai, persistance) | ✅ | ⏳ [test-materiel §10](test-materiel.md) (verrou après reboot) |
| 11 | `show` / `show_order`, image `builtin:` restituée | ✅ | n/a |
| 12 | Parallélisme, ambiance + scénario, STOP global < 1 s | ✅ | ⏳ [test-materiel §7, §8](test-materiel.md) |

**Jalon A : logique validée, câblage et Home Assistant réels non validés** (liste à cocher dans l'issue de suivi).

## Détail par critère

### 1. Composants créés par l'API
- C1 : `engine/tests/test_acceptance_jalon_a.py::test_c1_the_installation_is_built_from_the_api_and_every_object_is_testable` (installation complète depuis une configuration vide)
- `engine/tests/test_api_components.py::test_create_relay_hardware_is_rebuilt_and_ready`
- `engine/tests/test_api_components.py::test_manual_relay_test`
- `engine/tests/test_api_components.py::test_manual_button_press_reaches_the_subscribers`

### 2. Modes `latched` et `push`
- C2 : `engine/tests/test_acceptance_jalon_a.py::test_c2_latched_stays_closed_until_off_and_push_pulses_once_per_animation`
- `engine/tests/test_actions.py::test_latched_relay_on_off`
- `engine/tests/test_actions.py::test_push_relay_pulses_for_pulse_ms`
- `engine/tests/test_actions.py::test_second_trigger_during_animation_is_ignored`
- `engine/tests/test_gpio_relays.py::test_no_limit_means_the_relay_stays_on`

### 3. Corps JSON de Home Assistant
- C3 : `engine/tests/test_acceptance_jalon_a.py::test_c3_home_assistant_receives_only_the_authorised_parameters`
- `engine/tests/test_ha_contract.py::test_light_blocks_send_exactly_the_documented_bodies`
- `engine/tests/test_ha_contract.py::test_switch_blocks`
- `engine/tests/test_api_components.py::test_manual_light_test_refuses_unsupported_parameters`

### 4. `parallel`
- C4 : `engine/tests/test_acceptance_jalon_a.py::test_c4_parallel_drives_a_relay_and_a_light_at_the_same_time`
- `engine/tests/test_interpreter.py::test_parallel_all_waits_for_the_slowest_branch`
- `engine/tests/test_interpreter.py::test_parallel_first_stops_the_other_branches`

### 5. Bouton : appui court et appui long
- C5 : `engine/tests/test_acceptance_jalon_a.py::test_c5_short_press_starts_the_scenario_long_press_stops_it_within_a_second`
- `engine/tests/test_triggers.py::test_long_press_stops_everything_immediately`
- `engine/tests/test_triggers.py::test_physical_long_press_stops_a_running_scenario_in_under_a_second`
- `engine/tests/test_presses.py::test_long_press_fires_while_still_held_and_release_adds_nothing`

### 6. Coupure de Home Assistant
- C6 : `engine/tests/test_acceptance_jalon_a.py::test_c6_home_assistant_cut_during_a_run_leaves_relays_fine_and_traces_the_error`
- `engine/tests/test_ha_errors.py::test_run_continues_and_relays_stay_controlled_when_home_assistant_is_down`
- `engine/tests/test_ha_errors.py::test_on_error_abort_stops_the_run_with_the_ha_message`
- `engine/tests/test_ha_errors.py::test_slow_home_assistant_does_not_delay_every_block`

### 7. Redémarrage du Pi
- C7 : `engine/tests/test_acceptance_jalon_a.py::test_c7_after_a_pi_restart_relays_are_off_and_config_and_triggers_are_reloaded`
- `engine/tests/test_engine.py::test_pi_restart_after_a_crash_everything_is_at_rest_and_triggers_work`
- `engine/tests/test_engine.py::test_start_puts_everything_at_rest_before_anything_can_trigger`
- `engine/tests/test_engine.py::test_rest_state_is_retried_when_home_assistant_is_not_ready_at_boot`

### 8. Rejet localisé
- C8 : `engine/tests/test_acceptance_jalon_a.py::test_c8_invalid_programs_and_configs_are_rejected_with_a_located_error`
- `engine/tests/test_api_programs.py::test_invalid_shape_is_refused_with_errors_located_on_the_block`
- `engine/tests/test_api_programs.py::test_semantic_errors_are_refused_with_the_faulty_block`
- `engine/tests/test_engine.py::test_invalid_config_refuses_to_start`

### 9. Suite sans matériel
`make check` s'exécute sur un poste sans GPIO ni Home Assistant (plus de 700 tests, environ 30 s). Les broches passent par la fabrique simulée de gpiozero, Home Assistant par un faux serveur HTTP local.

### 10. Verrouillage
- `engine/tests/test_api_lock.py::test_every_write_route_answers_423_when_locked_except_the_documented_ones`
- `engine/tests/test_api_lock.py::test_run_requires_code_when_locked`
- `engine/tests/test_api_lock.py::test_stop_is_always_free`
- `engine/tests/test_api_lock.py::test_physical_triggers_keep_working_when_locked`
- `engine/tests/test_api_lock.py::test_five_wrong_codes_then_a_delay_applies`
- `engine/tests/test_api_lock.py::test_lock_survives_restart`
- `engine/tests/test_api_lock.py::test_code_is_never_stored_or_returned_in_clear`

### 11. `show` et images `builtin:`
- C11 : `engine/tests/test_acceptance_jalon_a.py::test_c11_show_programs_are_listed_in_order_and_builtin_images_are_kept`
- `engine/tests/test_api_programs.py::test_list_programs_sorted_for_the_show_mode`
- `engine/tests/test_api_components.py::test_list_and_get_components`

### 12. Parallélisme
- C12 : `engine/tests/test_acceptance_jalon_a.py::test_c12_parallelism_ambiance_scenario_and_stops`
- `engine/tests/test_interpreter.py::test_scripts_run_in_parallel`
- `engine/tests/test_runs.py::test_stop_all_stops_everything_instantly_and_applies_full_rest_state`

## Exigences hors critères numérotés (lot 6)
- Reprise après plantage ou gel : `engine/tests/test_watchdog.py::test_a_frozen_event_loop_stops_the_heartbeat` (simulation), procédure réelle [test-materiel §10](test-materiel.md).
- Journal en rotation et `/status` : `engine/tests/test_status_logs.py::test_the_log_rotates_and_keeps_a_bounded_number_of_archives`, `engine/tests/test_status_logs.py::test_status_gives_a_complete_diagnostic`.

## Ce qui reste pour clore le jalon A
Dérouler dans l'ordre sur le Pi : `test-materiel.md` (§0 à §10) puis `test-home-assistant.md`, et reporter les résultats (modèle de Pi, `active_low` constaté, capacités Hue / Twinkly retenues, latence) dans l'issue de suivi. Tout écart devient une issue corrective avant de passer à l'interface (lot 7).
