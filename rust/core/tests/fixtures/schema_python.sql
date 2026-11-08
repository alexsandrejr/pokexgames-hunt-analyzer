-- user_version = 10
-- index ix_chat_rewards_hunt_id ON chat_rewards
CREATE INDEX ix_chat_rewards_hunt_id ON chat_rewards (hunt_id);
-- index ix_dps_boss_pokemons_pokemon_id ON dps_boss_pokemons
CREATE INDEX ix_dps_boss_pokemons_pokemon_id ON dps_boss_pokemons (pokemon_id);
-- index ix_dps_damage_tests_boss_id ON dps_damage_tests
CREATE INDEX ix_dps_damage_tests_boss_id ON dps_damage_tests (boss_id);
-- index ix_dps_damage_tests_pokemon_id ON dps_damage_tests
CREATE INDEX ix_dps_damage_tests_pokemon_id ON dps_damage_tests (pokemon_id);
-- index ix_dps_damage_tests_skill_id ON dps_damage_tests
CREATE INDEX ix_dps_damage_tests_skill_id ON dps_damage_tests (skill_id);
-- index ix_dps_skills_pokemon_id ON dps_skills
CREATE INDEX ix_dps_skills_pokemon_id ON dps_skills (pokemon_id);
-- index ix_drops_chat_reward_id ON drops
CREATE INDEX ix_drops_chat_reward_id ON drops (chat_reward_id);
-- index ix_drops_hunt_id ON drops
CREATE INDEX ix_drops_hunt_id ON drops (hunt_id);
-- index ix_drops_item ON drops
CREATE INDEX ix_drops_item ON drops (item);
-- index ix_drops_item_lower ON drops
CREATE INDEX ix_drops_item_lower ON drops (lower(item));
-- index ix_enemies_defeated_enemy ON enemies_defeated
CREATE INDEX ix_enemies_defeated_enemy ON enemies_defeated (enemy);
-- index ix_enemies_defeated_enemy_lower ON enemies_defeated
CREATE INDEX ix_enemies_defeated_enemy_lower ON enemies_defeated (lower(enemy));
-- index ix_enemies_defeated_hunt_id ON enemies_defeated
CREATE INDEX ix_enemies_defeated_hunt_id ON enemies_defeated (hunt_id);
-- index ix_hunt_sessions_category ON hunt_sessions
CREATE INDEX ix_hunt_sessions_category ON hunt_sessions (category);
-- index ix_hunt_sessions_content_hash ON hunt_sessions
CREATE INDEX ix_hunt_sessions_content_hash ON hunt_sessions (content_hash);
-- index ix_hunt_sessions_identity ON hunt_sessions
CREATE INDEX ix_hunt_sessions_identity ON hunt_sessions (session_id, player, start_datetime);
-- index ix_hunt_sessions_player ON hunt_sessions
CREATE INDEX ix_hunt_sessions_player ON hunt_sessions (player);
-- index ix_hunt_sessions_session_id ON hunt_sessions
CREATE INDEX ix_hunt_sessions_session_id ON hunt_sessions (session_id);
-- index ix_hunt_sessions_start_datetime ON hunt_sessions
CREATE INDEX ix_hunt_sessions_start_datetime ON hunt_sessions (start_datetime);
-- index ix_supplies_hunt_id ON supplies
CREATE INDEX ix_supplies_hunt_id ON supplies (hunt_id);
-- index ix_supplies_item ON supplies
CREATE INDEX ix_supplies_item ON supplies (item);
-- index ix_supplies_item_lower ON supplies
CREATE INDEX ix_supplies_item_lower ON supplies (lower(item));
-- table chat_rewards ON chat_rewards
CREATE TABLE chat_rewards ( id INTEGER NOT NULL, hunt_id INTEGER NOT NULL, text TEXT NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(hunt_id) REFERENCES hunt_sessions (id) ON DELETE CASCADE );
-- table dps_boss_effectiveness ON dps_boss_effectiveness
CREATE TABLE dps_boss_effectiveness ( boss_id INTEGER NOT NULL, element VARCHAR(20) NOT NULL, level VARCHAR(20) NOT NULL, PRIMARY KEY (boss_id, element), FOREIGN KEY(boss_id) REFERENCES dps_bosses (id) ON DELETE CASCADE );
-- table dps_boss_pokemons ON dps_boss_pokemons
CREATE TABLE dps_boss_pokemons ( boss_id INTEGER NOT NULL, pokemon_id INTEGER NOT NULL, PRIMARY KEY (boss_id, pokemon_id), FOREIGN KEY(boss_id) REFERENCES dps_bosses (id) ON DELETE CASCADE, FOREIGN KEY(pokemon_id) REFERENCES dps_pokemons (id) ON DELETE CASCADE );
-- table dps_bosses ON dps_bosses
CREATE TABLE dps_bosses ( id INTEGER NOT NULL, name VARCHAR(200) NOT NULL, time_limit_seconds INTEGER NOT NULL, dummy VARCHAR(20) DEFAULT 'neutral' NOT NULL, damage_source VARCHAR(20) DEFAULT 'dummy' NOT NULL, element_1 VARCHAR(20), element_2 VARCHAR(20), PRIMARY KEY (id) );
-- table dps_damage_tests ON dps_damage_tests
CREATE TABLE dps_damage_tests ( id INTEGER NOT NULL, pokemon_id INTEGER NOT NULL, skill_id INTEGER, dummy VARCHAR(20) NOT NULL, boss_id INTEGER, damage_1 INTEGER, damage_2 INTEGER, damage_3 INTEGER, created_at DATETIME, updated_at DATETIME, PRIMARY KEY (id), FOREIGN KEY(pokemon_id) REFERENCES dps_pokemons (id) ON DELETE CASCADE, FOREIGN KEY(skill_id) REFERENCES dps_skills (id) ON DELETE CASCADE, FOREIGN KEY(boss_id) REFERENCES dps_bosses (id) ON DELETE CASCADE );
-- table dps_pokemons ON dps_pokemons
CREATE TABLE dps_pokemons ( id INTEGER NOT NULL, name VARCHAR(200) NOT NULL, note TEXT NOT NULL, basic_efficiency DOUBLE, basic_element VARCHAR(20), buff_cooldown DOUBLE, buff_basic_multiplier DOUBLE, buff_basic_duration DOUBLE, buff_next_spell_multiplier DOUBLE, PRIMARY KEY (id) );
-- table dps_settings ON dps_settings
CREATE TABLE dps_settings ( id INTEGER NOT NULL, basic_turn_seconds DOUBLE NOT NULL, target_melee_efficiency DOUBLE NOT NULL, default_efficiency DOUBLE NOT NULL, basic_efficiency DOUBLE NOT NULL, last_boss_id INTEGER, PRIMARY KEY (id), FOREIGN KEY(last_boss_id) REFERENCES dps_bosses (id) ON DELETE SET NULL );
-- table dps_skills ON dps_skills
CREATE TABLE dps_skills ( id INTEGER NOT NULL, pokemon_id INTEGER NOT NULL, position INTEGER NOT NULL, name VARCHAR(200) NOT NULL, shape VARCHAR(20) NOT NULL, reach VARCHAR(20) NOT NULL, cooldown DOUBLE NOT NULL, efficiency DOUBLE NOT NULL, element VARCHAR(20), PRIMARY KEY (id), FOREIGN KEY(pokemon_id) REFERENCES dps_pokemons (id) ON DELETE CASCADE );
-- table drops ON drops
CREATE TABLE drops ( hunt_id INTEGER NOT NULL, chat_reward_id INTEGER, id INTEGER NOT NULL, item VARCHAR(200) NOT NULL, count INTEGER NOT NULL, unit_price DOUBLE, total_price INTEGER, original_unit_price DOUBLE, original_total_price INTEGER, player VARCHAR(200), ignored BOOLEAN, PRIMARY KEY (id), FOREIGN KEY(hunt_id) REFERENCES hunt_sessions (id) ON DELETE CASCADE, FOREIGN KEY(chat_reward_id) REFERENCES chat_rewards (id) ON DELETE CASCADE );
-- table enemies_defeated ON enemies_defeated
CREATE TABLE enemies_defeated ( id INTEGER NOT NULL, hunt_id INTEGER NOT NULL, enemy VARCHAR(200) NOT NULL, player VARCHAR(200), count INTEGER NOT NULL, rare BOOLEAN, ignored BOOLEAN, PRIMARY KEY (id), FOREIGN KEY(hunt_id) REFERENCES hunt_sessions (id) ON DELETE CASCADE );
-- table hunt_sessions ON hunt_sessions
CREATE TABLE hunt_sessions ( id INTEGER NOT NULL, session_id INTEGER, player VARCHAR(200), start_datetime DATETIME, duration_seconds INTEGER, paused_seconds INTEGER, status VARCHAR(50), session_type VARCHAR(50), category VARCHAR(20) DEFAULT 'hunt' NOT NULL, kills INTEGER, kills_per_hour DOUBLE, rare_kills INTEGER, rare_kills_per_hour DOUBLE, experience INTEGER, experience_per_hour DOUBLE, profit INTEGER, profit_per_hour DOUBLE, supplies INTEGER, supplies_per_hour DOUBLE, raw_gains INTEGER, raw_gains_per_hour DOUBLE, damage_dealt INTEGER, damage_dealt_per_second DOUBLE, damage_taken INTEGER, damage_taken_per_second DOUBLE, time_to_next_level VARCHAR(50), time_to_next_level_seconds INTEGER, source_file VARCHAR(500), content_hash VARCHAR(64) NOT NULL, raw_json TEXT NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id) );
-- table item_prices ON item_prices
CREATE TABLE item_prices ( id INTEGER NOT NULL, "key" VARCHAR(200) NOT NULL, item VARCHAR(200) NOT NULL, unit_price DOUBLE NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id), UNIQUE ("key") );
-- table supplies ON supplies
CREATE TABLE supplies ( hunt_id INTEGER NOT NULL, id INTEGER NOT NULL, item VARCHAR(200) NOT NULL, count INTEGER NOT NULL, unit_price DOUBLE, total_price INTEGER, original_unit_price DOUBLE, original_total_price INTEGER, player VARCHAR(200), ignored BOOLEAN, PRIMARY KEY (id), FOREIGN KEY(hunt_id) REFERENCES hunt_sessions (id) ON DELETE CASCADE );
