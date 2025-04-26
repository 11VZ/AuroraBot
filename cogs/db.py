import aiosqlite

DB_PATH = 'queuebot.db'

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS queue_state (
                id INTEGER PRIMARY KEY, 
                queue_open INTEGER, 
                queue_message_id INTEGER,
                queue_channel_id INTEGER,
                current_testee INTEGER,
                previous_tier TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS queue_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS active_testers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_info (
                user_id INTEGER PRIMARY KEY,
                ign TEXT,
                region TEXT,
                last_test_timestamp INTEGER
            )
        ''')
        await db.commit()

async def save_queue_state(queue_open, queue_message_id, queue_channel_id, current_testee, previous_tier):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM queue_state')
        await db.execute(
            'INSERT INTO queue_state (queue_open, queue_message_id, queue_channel_id, current_testee, previous_tier) VALUES (?, ?, ?, ?, ?)',
            (int(queue_open), queue_message_id, queue_channel_id, current_testee, previous_tier)
        )
        await db.commit()

async def load_queue_state():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT queue_open, queue_message_id, queue_channel_id, current_testee, previous_tier FROM queue_state LIMIT 1') as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'queue_open': bool(row[0]),
                    'queue_message_id': row[1],
                    'queue_channel_id': row[2],
                    'current_testee': row[3],
                    'previous_tier': row[4]
                }
            return None

async def save_queue_members(members):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM queue_members')
        for user_id in members:
            await db.execute('INSERT INTO queue_members (user_id) VALUES (?)', (user_id,))
        await db.commit()

async def load_queue_members():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT user_id FROM queue_members') as cursor:
            return [row[0] async for row in cursor]

async def save_active_testers(testers):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM active_testers')
        for user_id in testers:
            await db.execute('INSERT INTO active_testers (user_id) VALUES (?)', (user_id,))
        await db.commit()

async def load_active_testers():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT user_id FROM active_testers') as cursor:
            return [row[0] async for row in cursor]

async def save_user_info(user_id, ign, region):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('REPLACE INTO user_info (user_id, ign, region) VALUES (?, ?, ?)', (user_id, ign, region))
        await db.commit()

async def get_user_info(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT ign, region, last_test_timestamp FROM user_info WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {'ign': row[0], 'region': row[1], 'last_test_timestamp': row[2]}
            return None

async def get_user_info_by_ign(ign):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT user_id, ign, region, last_test_timestamp FROM user_info WHERE ign = ?', (ign,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {'user_id': row[0], 'ign': row[1], 'region': row[2], 'last_test_timestamp': row[3]}
            return None

async def set_last_test_timestamp(user_id, timestamp):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE user_info SET last_test_timestamp = ? WHERE user_id = ?', (timestamp, user_id))
        await db.commit()
