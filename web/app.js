/* Local spectator client. All model text is rendered as text, never HTML. */
(() => {
  'use strict';

  // BEGIN LOCAL SPEECH CONTROLLER
/*
 * Local browser speech only. This factory makes no fetches and never selects a
 * remote voice. Root UI owns user consent, current perspective, and event IDs.
 * No audio plays on construction, enable(), or voiceschanged.
 *
 * onState({type, enabled, currentKey, language, reason?, available?})
 * Types: enabled, disabled, start, end, stop, error, voiceschanged.
 * Reasons: invalid_language, disabled, language_mismatch, invalid_text,
 * invalid_key, local_voice_unavailable, speech_unavailable, synthesis_failed,
 * synthesis_interrupted, queue_full.
 *
 * play(text, language, key): latest manual utterance wins; cancels old audio and
 * all pending live speech. enqueue(...) optionally supports live playback with
 * at most FOUR waiting utterances plus one active utterance. Overflow is rejected
 * with queue_full; duplicates return false without adding speech. The UI should
 * show overflow and let the viewer choose the current utterance manually.
 * stop() clears current and pending audio, retaining opt-in. disable() also
 * revokes opt-in. Both protect against stale cancellation/completion callbacks.
 */
function createSpeechPlayer({ synth, Utterance, onState = () => {} } = {}) {
  const MAX_PENDING = 4;
  const MAX_TEXT_CHARS = 1200;
  let optedIn = false;
  let selectedLanguage = null;
  let current = null;
  let pending = [];
  let generation = 0;

  function emit(type, extra = {}) {
    const update = { type, enabled: optedIn, currentKey: current ? current.key : null,
      language: selectedLanguage, ...extra };
    // A view callback must never break cancellation or advance the queue twice.
    try { onState(update); } catch (_) { /* UI errors do not grant audio access. */ }
  }
  function validLanguage(language) { return language === 'en' || language === 'zh'; }
  function supported() {
    return synth && typeof synth.getVoices === 'function' && typeof synth.speak === 'function'
      && typeof synth.cancel === 'function' && typeof Utterance === 'function';
  }
  function localVoice(language) {
    if (!supported() || !validLanguage(language)) return null;
    let voices;
    try { voices = synth.getVoices(); } catch (_) { return null; }
    if (!Array.isArray(voices)) return null;
    const matches = voices.filter((voice) => voice && voice.localService === true
      && typeof voice.lang === 'string'
      && voice.lang.toLowerCase().replaceAll('_', '-').split('-')[0] === language);
    const preferred = language === 'zh' ? ['zh-cn', 'zh-hans', 'zh'] : ['en-us', 'en-gb', 'en'];
    return matches.find((voice) => preferred.includes(voice.lang.toLowerCase().replaceAll('_', '-')))
      || matches[0] || null;
  }
  function fail(reason) { emit('error', { reason }); return false; }
  function cancel() {
    // Invalidate first: browsers can synchronously emit onend/onerror in cancel().
    generation += 1;
    current = null;
    pending = [];
    if (synth && typeof synth.cancel === 'function') {
      try { synth.cancel(); } catch (_) { emit('error', { reason: 'synthesis_failed' }); }
    }
  }
  function validate(text, language, key) {
    if (!optedIn) return fail('disabled');
    if (!validLanguage(language)) return fail('invalid_language');
    if (language !== selectedLanguage) return fail('language_mismatch');
    if (typeof text !== 'string' || !text.trim() || Array.from(text).length > MAX_TEXT_CHARS)
      return fail('invalid_text');
    if (!((typeof key === 'string' && key.length > 0 && key.length <= 200)
      || (typeof key === 'number' && Number.isFinite(key)))) return fail('invalid_key');
    if (!localVoice(language)) return fail('local_voice_unavailable');
    return true;
  }
  function begin(item) {
    if (!optedIn || item.language !== selectedLanguage) return false;
    const voice = localVoice(item.language);
    if (!voice) { pending = []; return fail('local_voice_unavailable'); }
    const ticket = ++generation;
    let utterance;
    try {
      utterance = new Utterance(item.text);
      // Never leave voice unset: that could select the browser's remote default.
      utterance.voice = voice;
      utterance.lang = voice.lang;
    } catch (_) { pending = []; return fail('synthesis_failed'); }
    current = { ...item, utterance, ticket };
    utterance.onend = () => {
      if (!optedIn || !current || current.ticket !== ticket || generation !== ticket) return;
      current = null;
      emit('end', { completedKey: item.key });
      // onState can call stop(), disable(), or play(). Respect that reentrancy.
      if (!optedIn || generation !== ticket || current) return;
      const next = pending.shift();
      if (next) begin(next);
    };
    utterance.onerror = () => {
      if (!current || current.ticket !== ticket || generation !== ticket) return;
      generation += 1;
      current = null;
      pending = [];
      fail('synthesis_interrupted');
    };
    emit('start');
    // A callback may revoke opt-in before speak() is reached.
    if (!optedIn || !current || current.ticket !== ticket || generation !== ticket) return false;
    try { synth.speak(utterance); }
    catch (_) {
      if (current && current.ticket === ticket) {
        generation += 1; current = null; pending = []; fail('synthesis_failed');
      }
      return false;
    }
    return true;
  }
  function enable(language) {
    if (!validLanguage(language)) return fail('invalid_language');
    if (!supported()) return fail('speech_unavailable');
    if (!localVoice(language)) {
      optedIn = false;
      selectedLanguage = language;
      cancel();
      return fail('local_voice_unavailable');
    }
    if (selectedLanguage !== language) cancel();
    selectedLanguage = language;
    optedIn = true;
    emit('enabled');
    return true;
  }
  function disable() {
    optedIn = false;
    cancel();
    emit('disabled');
  }
  function stop() { cancel(); emit('stop'); }
  function play(text, language, key) {
    if (!validate(text, language, key)) return false;
    cancel();
    return begin({ text: text.trim(), language, key });
  }
  function enqueue(text, language, key) {
    if (!validate(text, language, key)) return false;
    if ((current && current.key === key) || pending.some((item) => item.key === key)) return false;
    const item = { text: text.trim(), language, key };
    if (!current) return begin(item);
    if (pending.length >= MAX_PENDING) return fail('queue_full');
    pending.push(item);
    return true;
  }
  function voicesChanged() {
    emit('voiceschanged', { available: selectedLanguage ? Boolean(localVoice(selectedLanguage)) : false });
  }
  if (synth && typeof synth.addEventListener === 'function') synth.addEventListener('voiceschanged', voicesChanged);
  else if (synth && 'onvoiceschanged' in synth) {
    const previous = synth.onvoiceschanged;
    synth.onvoiceschanged = function (event) {
      try { if (typeof previous === 'function') previous.call(this, event); }
      finally { voicesChanged(); }
    };
  }
  return {
    enable, disable, play, stop, enqueue,
    get enabled() { return optedIn; },
    get currentKey() { return current ? current.key : null; },
  };
}

  // END LOCAL SPEECH CONTROLLER

  const I18N = {
    en: {
      brandCaption: 'AN AI SOCIAL EXPERIMENT', localSession: 'LOCAL SESSION', newGame: 'New game',
      eyebrow: 'TWELVE MINDS. ONE HIDDEN TRUTH.', headline: 'The village is listening.',
      introCopy: 'Watch alliances form, stories unravel, and every word become evidence.',
      players: 'PLAYERS', rulesTag: 'STANDARD · RULES V1', demoTitle: 'Scripted demonstration',
      demoCopy: 'These players are smoke-test scripts, not a measure of AI capability.',
      mixedDemoTitle: 'Includes scripted players', mixedDemoCopy: 'Some seats use demonstration scripts. Treat this as a mixed test, not a controlled AI comparison.',
      play: 'Play', pause: 'Pause', perspective: 'Perspective', mystery: 'Mystery', omniscient: 'Omniscient',
      follow: 'Follow a player', village: 'The village', speaking: 'Speaking', speakingNow: 'Speaking', voiceOn: 'Voice on', voiceOff: 'Voice off', readSpeech: 'Read aloud', stopReading: 'Stop reading', readingNow: 'Reading {name}', voiceHint: 'Read new player speech and public referee announcements with a local voice. Past records can be read individually.', voiceMissing: 'No local voice is available for this game language. Install a system voice and try again.', voiceFailed: 'Speech playback is unavailable. Try again in a supported browser.', voiceBacklog: 'Voice playback fell behind and was stopped. Select a speech to read or enable voice again.', candidate: 'Running', withdrawn: 'Withdrawn', nominated: 'Ran', elected: 'Elected', currentSpeaker: '{name} is speaking', closeDetails: 'Close details', details: 'Game details', sheriff: 'Sheriff',
      eliminated: 'Eliminated', alive: 'alive', hiddenRole: 'Unknown role', transcript: 'The conversation',
      autoScroll: 'Follow latest ↓', autoScrollOff: 'Follow latest', waitingTitle: 'Before the first whisper',
      waitingCopy: 'Start the game to watch the village come alive.', transcriptNote: 'Claims are not confirmed roles.',
      timeline: 'TIMELINE', live: 'LIVE', playerDetail: 'Player dossier', voteLedger: 'Voting record',
      publicRecord: 'PUBLIC RECORD', footer: 'A game of imperfect information. A window into artificial minds.',
      export: 'Export archive ↗', nextSession: 'THE NEXT SESSION', setupTitle: 'Gather the village.',
      setupCopy: 'Choose the players before the first night. Their configurations and speech language remain fixed throughout the game.',
      gameLanguage: 'Game & player speech language', seed: 'Game seed',
      credentialsNote: 'Live providers read credentials from the server environment. No API keys are entered or stored in this interface.',
      configurePlayers: 'Configure twelve players', fixedAtStart: 'FIXED AT START',
      newGameWarning: 'Starting a new game replaces the current session. Export its archive first if you want to keep it.',
      cancel: 'Cancel', createGame: 'Create game', exportTitle: 'Reveal the full archive?',
      exportWarning: 'This download contains every hidden role, private action, player note, and provider request. It will spoil a mystery game. Keep it away from active players.',
      downloadArchive: 'Download archive', centerCaption: 'Secrets move in the dark.',
      mysteryNote: 'PUBLIC VIEW · Roles stay hidden after death. No private actions or notes are shown.',
      omniscientNote: 'ALL-SEING VIEW · You can see secrets that the players cannot. This view never feeds back into play.',
      playerNote: 'PLAYER VIEW · Only information available to seat {seat} at this point in the game.',
      paused: 'Paused', running: 'Playing', finished: 'Finished', error: 'Needs attention', replay: 'Replay',
      night: 'NIGHT', day: 'DAY', englishGame: 'ENGLISH GAME', chineseGame: 'CHINESE GAME',
      goodWins: 'The village prevails.', wolvesWin: 'The wolves prevail.', endCaption: 'Every secret has a story.',
      nightTitle: 'The village sleeps', dayTitle: 'Every word matters',
      dayCaption: 'Listen closely. Trust carefully.', events: '{count} events',
      referee: 'Referee', private: 'PRIVATE', wolfTeam: 'WOLF TEAM', public: 'PUBLIC', seat: 'Seat {seat}',
      noVotes: 'No ballots have been published yet.', noNotes: 'No private notes available in this perspective.',
      notes: 'PRIVATE STRATEGY NOTES', notesDisclaimer: 'AI-authored self-report, not access to internal model reasoning.',
      noConfig: 'Configuration unavailable', demoProvider: 'Scripted demo', personality: 'Personality',
      playerName: 'Player name', modelId: 'Model ID', temperature: 'Temperature', tokens: 'Output tokens',
      subscriptionBudget: 'ChatGPT plan usage: temperature and output-token overrides are not sent.',
      gameReplaced: 'A new village is ready. Player settings are now fixed.',
      networkError: 'Could not reach the local game server. Check that it is running, then try again.',
      requestFailed: 'The request could not be completed.', invalidPlayers: 'Enter a name and model ID for every seat.',
      selectSeat: 'Select a seat to inspect its permitted information.', advanceTitle: 'Advance one decision batch',
      previousCheckpoint: 'Previous checkpoint', followSeat: 'Follow seat', closeSetup: 'Close setup',
      dossierSeat: 'Player dossier seat', archiveFailed: 'The archive could not be downloaded.',
      phase: 'Phase', role: 'Role', wolf: 'Wolf', villager: 'Villager', seer: 'Seer', witch: 'Witch', hunter: 'Hunter', idiot: 'Idiot',
      ready: 'Ready', vote: 'Vote', abstain: 'Abstain', currentGameLanguage: 'Speech language: {language}',
      voteTitle: 'Day {day} · {kind}', replayHint: 'Historical checkpoint · original speech is preserved',
      noData: 'No public voting details.', inspect: 'Inspect seat {seat}',
      historyControls: 'Viewing history. Return to LIVE to control the current game.',
      deepseekPreset: 'Use Flash · fast', deepseekHighPreset: 'Use Flash · high thinking', testConnection: 'Test connection', testConnectionBusy: 'Testing…',
      deepseekPresetCopy: 'Fast: thinking off, 8,192 tokens. High: thinking high, 32,768 tokens. Applies to the next game only.',
      deepseekKeyHelp: 'Set DEEPSEEK_API_KEY in your local .env file, then restart the server. Keep the key out of this interface.',
      connectionCost: 'Testing sends one small API request. It does not start or change a game.',
      keyChecking: 'Checking key setup…', keyConfigured: 'KEY CONFIGURED', keyMissing: 'KEY NOT CONFIGURED', keyUnknown: 'SETUP STATUS UNAVAILABLE',
      connectionChecking: 'Testing DeepSeek Flash… waiting for the model response.', connectionSuccess: 'DeepSeek Flash connected successfully.',
      connectionFailure: 'Could not connect to DeepSeek Flash.', flashApplied: 'DeepSeek Flash is selected for all twelve seats. Names and personalities are preserved.',
      thinking: 'Thinking', thinkingEnabled: 'Enabled', thinkingDisabled: 'Disabled', reasoningEffort: 'Reasoning effort',
      effortLow: 'Low', effortHigh: 'High', effortMax: 'Maximum', modelDefault: 'Model default',
      temperatureThinking: 'Temperature is not sent when thinking is enabled.',
      interactionMode: 'Interaction', toolHarness: 'Tool harness', jsonAction: 'JSON action',
      phases: { setup: 'The lineup', night: 'Night actions', day: 'Dawn', election: 'Sheriff election', voting: 'Exile vote', campaign: 'Sheriff campaign', tie_speech: 'Tie speeches', sheriff_ballots: 'Sheriff ballots', exile_ballots: 'Exile ballots', wolf_discussion: 'Wolf council', wolf_vote: 'Night attack', witch: 'Witch acts', seer: 'Seer investigates', hunter_status: 'Hunter status', dawn: 'Dawn', sheriff_nomination: 'Sheriff nominations', sheriff_speech: 'Sheriff campaign', sheriff_withdrawal: 'Candidate withdrawal', sheriff_vote: 'Sheriff election', sheriff_runoff: 'Election runoff', discussion: 'Village discussion', speech: 'Village discussion', exile_vote: 'Exile vote', vote: 'Exile vote', runoff: 'Runoff vote', last_words: 'Last words', badge: 'Sheriff badge', explosion: 'Wolf reveal', finished: 'Game over' },
    },
    zh: {
      brandCaption: '一场 AI 社交推理实验', localSession: '本地对局', newGame: '新对局',
      eyebrow: '十二个头脑，一个隐藏的真相。', headline: '村庄，正在倾听。',
      introCopy: '看同盟建立，谎言瓦解，让每一句话都成为线索。',
      players: '位玩家', rulesTag: '标准局 · 规则 V1', demoTitle: '脚本演示',
      demoCopy: '当前玩家由测试脚本驱动，演示结果不代表 AI 能力。',
      mixedDemoTitle: '包含脚本玩家', mixedDemoCopy: '部分席位使用演示脚本。本局属于混合测试，不能视为受控的 AI 能力对比。',
      play: '开始', pause: '暂停', perspective: '观战视角', mystery: '悬疑视角', omniscient: '全知视角',
      follow: '跟随玩家', village: '村庄席位', speaking: '当前发言', speakingNow: '发言中', voiceOn: '朗读：开', voiceOff: '朗读：关', readSpeech: '朗读', stopReading: '停止朗读', readingNow: '正在朗读 {name}', voiceHint: '用对局语言的本地语音朗读新发言和法官公开播报；过去的记录可单独点读。', voiceMissing: '没有可用的本地对局语言语音，请安装对应的系统语音后重试。', voiceFailed: '语音播放暂不可用，请重试或使用支持语音的浏览器。', voiceBacklog: '朗读已落后于对局，已停止播放。可点选发言朗读，或重新开启。', candidate: '上警', withdrawn: '退水', nominated: '曾上警', elected: '当选', currentSpeaker: '{name} 正在发言', closeDetails: '关闭详情', details: '对局详情', sheriff: '警长',
      eliminated: '已出局', alive: '存活', hiddenRole: '身份未知', transcript: '场上记录',
      autoScroll: '跟随最新 ↓', autoScrollOff: '跟随最新', waitingTitle: '第一声低语之前',
      waitingCopy: '开始对局，静候村庄苏醒。', transcriptNote: '身份宣称不等于身份确认。',
      timeline: '时间线', live: '实时', playerDetail: '玩家档案', voteLedger: '投票记录',
      publicRecord: '公开信息', footer: '不完全信息的博弈，观察人工智能的窗口。',
      export: '导出存档 ↗', nextSession: '下一场对局', setupTitle: '让村庄集结。',
      setupCopy: '首夜前配置所有玩家。玩家配置与发言语言在本局开始后保持不变。',
      gameLanguage: '游戏与玩家发言语言', seed: '对局随机种子',
      credentialsNote: '在线模型从服务器环境变量读取凭据。此界面不输入、也不保存任何 API 密钥。',
      configurePlayers: '配置十二位玩家', fixedAtStart: '开局后固定',
      newGameWarning: '新对局会替换当前对局。如需保留，请先导出完整档案。',
      cancel: '取消', createGame: '创建对局', exportTitle: '查看完整隐藏信息？',
      exportWarning: '下载内容包含所有隐藏身份、私密行动、玩家笔记和模型请求，会剧透悬疑对局。请勿向仍在游戏中的玩家提供这些内容。',
      downloadArchive: '下载档案', centerCaption: '秘密在夜色中流动。',
      mysteryNote: '公开视角 · 出局不翻牌，不展示私密行动与笔记。',
      omniscientNote: '全知视角 · 你能看到玩家不知道的秘密。观战信息永不回传给玩家。',
      playerNote: '玩家视角 · 仅展示 {seat} 号玩家在此刻能获得的信息。',
      paused: '已暂停', running: '进行中', finished: '已结束', error: '需要处理', replay: '回放',
      night: '夜晚', day: '白天', englishGame: '英文对局', chineseGame: '中文对局',
      goodWins: '好人阵营获胜。', wolvesWin: '狼人阵营获胜。', endCaption: '每个秘密，都有来处。',
      nightTitle: '村庄入眠', dayTitle: '每句话，都有分量', dayCaption: '仔细倾听，谨慎相信。', events: '{count} 条记录',
      referee: '法官', private: '私密', wolfTeam: '狼队', public: '公开', seat: '{seat} 号',
      noVotes: '尚未公布投票结果。', noNotes: '当前视角没有可查看的私密笔记。',
      notes: '私密策略笔记', notesDisclaimer: '由 AI 自行撰写的说明，不代表模型内部思维过程。',
      noConfig: '暂无配置信息', demoProvider: '脚本演示', personality: '性格',
      playerName: '玩家名称', modelId: '模型 ID', temperature: '温度', tokens: '输出额度',
      subscriptionBudget: 'ChatGPT 订阅模式：不发送温度与输出 token 数覆盖参数。',
      gameReplaced: '新村庄已就绪。本局玩家配置已固定。',
      networkError: '无法连接本地游戏服务器。请确认服务器已启动后重试。',
      requestFailed: '请求未能完成。', invalidPlayers: '请填写每个席位的玩家名称与模型 ID。',
      selectSeat: '选择一个席位，查看其可见信息。', advanceTitle: '推进一批决策',
      previousCheckpoint: '上一个回放节点', followSeat: '跟随席位', closeSetup: '关闭设置',
      dossierSeat: '玩家档案席位', archiveFailed: '无法下载对局档案。',
      phase: '阶段', role: '身份', wolf: '狼人', villager: '平民', seer: '预言家', witch: '女巫', hunter: '猎人', idiot: '白痴',
      ready: '已就绪', vote: '投票', abstain: '弃票', currentGameLanguage: '发言语言：{language}',
      voteTitle: '第 {day} 天 · {kind}', replayHint: '历史回放节点 · 发言保留原始语言',
      noData: '暂无公开票型详情。', inspect: '查看 {seat} 号玩家',
      historyControls: '正在查看历史回放。返回“实时”后可控制当前对局。',
      deepseekPreset: '十二席 Flash · 快速', deepseekHighPreset: '十二席 Flash · 高思考', testConnection: '测试连接', testConnectionBusy: '正在测试…',
      deepseekPresetCopy: '快速：关闭思考，8,192 token；高思考：high，32,768 token。均使用工具，仅应用于新对局。',
      deepseekKeyHelp: '在本地 .env 文件中设置 DEEPSEEK_API_KEY，然后重启服务器。请勿在此界面输入密钥。',
      connectionCost: '测试会发送一次小型 API 请求，不会开始或更改任何对局。',
      keyChecking: '正在检查密钥配置…', keyConfigured: '密钥已配置', keyMissing: '尚未配置密钥', keyUnknown: '无法获取配置状态',
      connectionChecking: '正在测试 DeepSeek Flash…等待模型响应。', connectionSuccess: 'DeepSeek Flash 连接成功。',
      connectionFailure: '无法连接 DeepSeek Flash。', flashApplied: '十二席已选择 DeepSeek Flash，玩家名称与性格保持不变。',
      thinking: '思考模式', thinkingEnabled: '开启', thinkingDisabled: '关闭', reasoningEffort: '推理强度',
      effortLow: '低', effortHigh: '高', effortMax: '最高', modelDefault: '模型默认',
      temperatureThinking: '开启思考模式时不发送温度参数。',
      interactionMode: '交互方式', toolHarness: '工具交互', jsonAction: 'JSON 动作',
      phases: { setup: '身份配置', night: '夜间行动', day: '天亮', election: '警长竞选', voting: '放逐投票', campaign: '警上发言', tie_speech: '平票 PK 发言', sheriff_ballots: '警长票型', exile_ballots: '放逐票型', wolf_discussion: '狼队商议', wolf_vote: '狼队落刀', witch: '女巫行动', seer: '预言家查验', hunter_status: '猎人状态', dawn: '天亮', sheriff_nomination: '上警报名', sheriff_speech: '警上发言', sheriff_withdrawal: '退水', sheriff_vote: '警长竞选投票', sheriff_runoff: '警上平票 PK', discussion: '放逐发言', speech: '放逐发言', exile_vote: '放逐投票', vote: '放逐投票', runoff: '平票 PK', last_words: '遗言', badge: '警徽处理', explosion: '狼人自爆', finished: '游戏结束' },
    },
  };

  const $ = (id) => document.getElementById(id);
  const state = {
    locale: readLocale(), mode: 'mystery', followSeat: 1, detailSeat: 1,
    at: null, snapshot: null, busy: false, autoScroll: true, requestVersion: 0,
    lastEventSignature: '', draft: null, providerInfo: null, providerLoading: false,
    connectionChecking: false, connectionResult: null, flashApplied: false,
    detailsPanel: 'dossier', drawerReturnSeat: null,
    autoSpeech: false, speechEpoch: 0, speechScope: '', speechEvents: null, speechStep: null, speechError: '', speechGameLanguage: null, speechHandlingError: false,
  };
  const names = {
    en: ['Rowan', 'Iris', 'Ash', 'Juniper', 'Sage', 'Wren', 'Hazel', 'Reed', 'Laurel', 'Finch', 'Briar', 'Clover'],
    zh: ['青禾', '白露', '松影', '云杉', '知秋', '听风', '月见', '芦苇', '桂枝', '山雀', '荆棘', '三叶'],
  };
  const personalities = {
    en: ['Methodical and observant', 'Warm but skeptical', 'Bold and direct', 'Patient and analytical', 'Quiet and precise', 'Playful and persuasive', 'Cautious and empathetic', 'Pragmatic and decisive', 'Curious and diplomatic', 'Energetic and questioning', 'Independent and challenging', 'Calm and collaborative'],
    zh: ['细致谨慎，善于观察', '温和亲切，保持怀疑', '大胆直接，立场鲜明', '耐心分析，重视证据', '沉稳寡言，表达精准', '风趣灵活，善于说服', '谨慎共情，关注细节', '务实果断，注重行动', '好奇理性，善于沟通', '积极提问，思维活跃', '独立判断，敢于质疑', '冷静合作，善于倾听'],
  };
  const avatarColors = ['#485344', '#4c5140', '#3d514b', '#54513d', '#455547', '#424c50', '#4f5845', '#4c5041', '#3f5143', '#54533e', '#455343', '#4c594b'];

  const speechPlayer = createSpeechPlayer({ synth: window.speechSynthesis,
    Utterance: window.SpeechSynthesisUtterance, onState: onSpeechState });
  const speechKinds = new Set(['speech', 'speak', 'campaign', 'tie_speech', 'last_words', 'wolf_discussion', 'wolf_chat']);
  function speechKey(index) { return `${state.speechEpoch}:${index}`; }
  function isSpeech(event) { return Boolean(event.seat) && speechKinds.has(event.kind); }
  function isNarratable(event) { return isSpeech(event) || (!isPrivate(event) && Boolean(eventText(event)?.trim())); }
  function narrationName(event) { return isSpeech(event) ? playerName(event.seat) : t('referee'); }
  function speechLanguage() { return state.snapshot?.language || state.locale; }
  function resetSpeechView() {
    speechPlayer.stop(); state.speechEpoch += 1; state.speechEvents = null;
    state.speechScope = ''; state.speechStep = null; state.speechError = '';
  }
  function changePerspective() {
    resetSpeechView(); state.snapshot = null; state.lastEventSignature = ''; render(); refresh();
  }
  function onSpeechState(update) {
    if (update.type === 'error') {
      if (state.speechHandlingError) return;
      state.autoSpeech = false; state.speechHandlingError = true;
      try { speechPlayer.disable(); } finally { state.speechHandlingError = false; }
      state.speechError = update.reason;
    } else if (['enabled', 'start', 'stop', 'disabled'].includes(update.type)) state.speechError = '';
    if (update.type === 'voiceschanged' && update.available) state.speechError = '';
    renderSpeechControls();
    if ($('seats')) renderSeats(getPlayers());
  }
  function renderSpeechControls() {
    const toggle = $('speech-toggle');
    if (!toggle) return;
    toggle.textContent = t(state.autoSpeech ? 'voiceOn' : 'voiceOff');
    toggle.setAttribute('aria-pressed', String(state.autoSpeech)); toggle.title = t('voiceHint');
    toggle.disabled = !state.snapshot || !window.speechSynthesis || !window.SpeechSynthesisUtterance;
    let status = '';
    if (state.speechError) status = t(state.speechError === 'local_voice_unavailable' ? 'voiceMissing'
      : state.speechError === 'queue_full' ? 'voiceBacklog' : 'voiceFailed');
    else if (speechPlayer.currentKey != null) {
      const index = Number(String(speechPlayer.currentKey).split(':')[1]);
      const event = state.snapshot?.events?.[index];
      if (event) status = t('readingNow', { name: narrationName(event) });
    }
    $('speech-status').hidden = !status; $('speech-status').textContent = status; $('speech-status').title = status;
    document.querySelectorAll('[data-speech-key]').forEach((button) => {
      const reading = button.dataset.speechKey === speechPlayer.currentKey;
      button.textContent = t(reading ? 'stopReading' : 'readSpeech');
      button.setAttribute('aria-pressed', String(reading));
      button.setAttribute('aria-label', `${t(reading ? 'stopReading' : 'readSpeech')} · ${button.dataset.speechReferee === 'true' ? t('referee') : playerName(button.dataset.speechSeat)}`);
      button.closest('.event')?.classList.toggle('reading', reading);
    });
  }
  function syncSpeech(snapshot) {
    if (!snapshot) return;
    const scope = [state.mode, state.followSeat, state.at === null ? 'live' : `replay-${state.at}`, snapshot.language].join(':');
    const events = snapshot.events || [], signatures = events.map((event) => JSON.stringify(event));
    const reset = scope !== state.speechScope || state.speechEvents === null
      || signatures.length < state.speechEvents.length || state.speechEvents.some((text, index) => text !== signatures[index])
      || (state.speechStep !== null && snapshot.step < state.speechStep);
    const previousCount = reset ? events.length : state.speechEvents.length;
    if (reset) {
      if (state.speechGameLanguage != null && state.speechGameLanguage !== snapshot.language) {
        state.autoSpeech = false; speechPlayer.disable();
      } else speechPlayer.stop();
      state.speechEpoch += 1;
      // A reset changes keys even when this checkpoint has the same public text.
      state.lastEventSignature = ''; renderEvents(events);
    }
    state.speechScope = scope; state.speechEvents = signatures; state.speechStep = snapshot.step;
    state.speechGameLanguage = snapshot.language;
    if (!reset && state.autoSpeech && state.at === null) {
      for (let index = previousCount; index < events.length; index++) {
        if (isNarratable(events[index]) && !speechPlayer.enqueue(eventText(events[index]), snapshot.language, speechKey(index))) break;
      }
    }
    renderSpeechControls();
  }
  function readLocale() {
    try { const saved = localStorage.getItem('werewolf-locale'); if (saved === 'en' || saved === 'zh') return saved; } catch (_) { /* Storage may be disabled. */ }
    return navigator.language?.startsWith('zh') ? 'zh' : 'en';
  }
  function t(key, vars = {}) {
    let value = I18N[state.locale][key] ?? I18N.en[key] ?? key;
    if (typeof value !== 'string') return key;
    return value.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? ''));
  }
  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  }
  function setLocale(locale) {
    state.locale = locale;
    try { localStorage.setItem('werewolf-locale', locale); } catch (_) { /* No persistence required. */ }
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
    document.title = locale === 'zh' ? '狼人杀 — 观战' : 'Werewolf — Spectator';
    document.querySelectorAll('[data-i18n]').forEach((element) => { element.textContent = t(element.dataset.i18n); });
    $('locale-en').classList.toggle('active', locale === 'en');
    $('locale-zh').classList.toggle('active', locale === 'zh');
    $('locale-en').setAttribute('aria-pressed', String(locale === 'en'));
    $('locale-zh').setAttribute('aria-pressed', String(locale === 'zh'));
    for (const [id, key] of [['step', 'advanceTitle'], ['replay-back', 'previousCheckpoint'], ['follow-seat', 'followSeat'], ['setup-close', 'closeSetup'], ['detail-seat', 'dossierSeat'], ['details-close', 'closeDetails']]) {
      $(id).setAttribute('aria-label', t(key)); $(id).title = t(key);
    }
    $('replay-range').setAttribute('aria-label', t('timeline'));
    $('transcript').setAttribute('aria-label', t('transcript'));
    document.querySelector('.drawer-tabs').setAttribute('aria-label', t('details'));
    setDetailsPanel(state.detailsPanel);
    if (state.draft) renderSetup();
    state.lastEventSignature = '';
    render();
  }

  async function api(path, body) {
    let response;
    try {
      response = await fetch(path, body === undefined ? { cache: 'no-store' } : {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
    } catch (_) { throw new Error(t('networkError')); }
    let data;
    try { data = await response.json(); } catch (_) { throw new Error(t('requestFailed')); }
    if (!response.ok) throw new Error(typeof data.error === 'string' ? data.error : t('requestFailed'));
    return data;
  }
  function notice(message, error = false) {
    $('notice').hidden = !message;
    $('notice').textContent = message || '';
    $('notice').setAttribute('role', error ? 'alert' : 'status');
  }
  async function refresh() {
    const version = ++state.requestVersion;
    const query = new URLSearchParams({ mode: state.mode });
    if (state.mode === 'player') query.set('seat', String(state.followSeat));
    if (state.at !== null) query.set('at', String(state.at));
    try {
      const snapshot = await api(`/api/state?${query}`);
      if (version !== state.requestVersion) return;
      state.snapshot = snapshot;
      if (snapshot.error) notice(typeof snapshot.error === 'string' ? snapshot.error : t('requestFailed'), true);
      else notice('');
      render();
    } catch (error) {
      if (version === state.requestVersion) notice(error.message, true);
    }
  }
  async function command(path) {
    if (state.busy) return;
    state.busy = true; renderControls();
    try {
      await api(path, {});
      state.at = null;
      await refresh();
    } catch (error) { notice(error.message, true); }
    finally { state.busy = false; renderControls(); }
  }
  function phaseName(phase) {
    return I18N[state.locale].phases[phase] || (typeof phase === 'string' ? phase.replaceAll('_', ' ') : t('ready'));
  }
  function roleName(role) { return role && I18N[state.locale][role] ? t(role) : t('hiddenRole'); }
  function getPlayers() {
    return state.snapshot?.players || names[state.locale].map((name, i) => ({ seat: i + 1, name, alive: true }));
  }
  function playerFor(seat) { return getPlayers().find((player) => Number(player.seat) === Number(seat)); }
  function configFor(seat) {
    const configs = state.snapshot?.configs;
    return Array.isArray(configs) ? configs.find((config) => Number(config.seat) === Number(seat)) : configs?.[seat];
  }
  function playerName(seat) { return playerFor(seat)?.name || t('seat', { seat }); }
  function permittedRole(player) { return player?.role || player?.revealed_role || null; }
  function phaseIsNight(snapshot) {
    return ['night', 'wolf_discussion', 'wolf_vote', 'witch', 'seer', 'hunter_status'].includes(snapshot?.phase);
  }

  function renderControls() {
    const status = state.snapshot?.status || 'paused';
    const running = status === 'running';
    const finished = status === 'finished' || Boolean(state.snapshot?.winner);
    const historical = state.at !== null;
    const liveBusy = Boolean(state.snapshot?.busy || state.snapshot?.playing);
    $('play').replaceChildren(node('span', '', running ? 'Ⅱ' : '▶'), node('span', '', t(running ? 'pause' : 'play')));
    $('play').disabled = historical || state.busy || finished || !state.snapshot;
    $('play').title = historical ? t('historyControls') : t(running ? 'pause' : 'play');
    $('step').disabled = historical || state.busy || running || liveBusy || finished || !state.snapshot;
    $('step').title = historical ? t('historyControls') : t('advanceTitle');
    $('setup-open').disabled = state.busy || running || liveBusy;
    $('status-label').textContent = state.at === null ? t(status) : t('replay');
    $('status-dot').className = status;
    $('follow-seat').hidden = state.mode !== 'player';
    $('perspective').value = state.mode;
    $('autoscroll').textContent = t(state.autoScroll ? 'autoScroll' : 'autoScrollOff');
    $('autoscroll').setAttribute('aria-pressed', String(state.autoScroll));
    const max = Number(state.snapshot?.max_step || 0);
    const index = state.at === null ? Number(state.snapshot?.step ?? max) : state.at;
    $('replay-range').max = String(max);
    $('replay-range').value = String(Math.min(index, max));
    $('replay-position').textContent = `${index} / ${max}`;
    $('go-live').classList.toggle('replaying', state.at !== null);
    $('go-live').title = state.at === null ? t('live') : t('replayHint');
    $('replay-back').disabled = !state.snapshot || index <= 0;
    $('export').disabled = !state.snapshot;
    renderSpeechControls();
  }
  function render() {
    renderControls();
    const snapshot = state.snapshot;
    const players = getPlayers();
    const configs = snapshot?.configs || [];
    const configList = Array.isArray(configs) ? configs : Object.values(configs);
    const demos = configList.filter((config) => config.provider === 'demo').length;
    $('demo-notice').hidden = snapshot ? demos === 0 : false;
    $('demo-notice').querySelector('strong').textContent = t(demos && demos < configList.length ? 'mixedDemoTitle' : 'demoTitle');
    $('demo-notice').querySelector('span:last-child').textContent = t(demos && demos < configList.length ? 'mixedDemoCopy' : 'demoCopy');
    const language = snapshot?.language || state.locale;
    $('game-language').textContent = t(language === 'zh' ? 'chineseGame' : 'englishGame');
    $('game-language').title = t('currentGameLanguage', { language: language === 'zh' ? '中文' : 'English' });
    $('alive-count').textContent = `${players.filter((player) => player.alive).length} / 12 ${t('alive')}`;
    const night = phaseIsNight(snapshot);
    $('village').classList.toggle('is-day', !night && Boolean(snapshot));
    $('day-label').textContent = `${t(night || !snapshot ? 'night' : 'day')} ${snapshot?.day || 1}`;
    $('phase-label').textContent = snapshot?.winner ? t(snapshot.winner === 'wolves' ? 'wolvesWin' : 'goodWins') : snapshot ? phaseName(snapshot.phase) : t('nightTitle');
    $('perspective-note').textContent = t(state.mode === 'player' ? 'playerNote' : state.mode === 'omniscient' ? 'omniscientNote' : 'mysteryNote', { seat: state.followSeat }) + (state.at !== null ? ` ${t('historyControls')}` : '');
    $('perspective-note').title = $('perspective-note').textContent;
    fillSeatSelect($('follow-seat'), state.followSeat);
    fillSeatSelect($('detail-seat'), state.detailSeat);
    const speakers = (snapshot?.current_speakers || []).map((seat) => playerName(typeof seat === 'object' ? seat.seat : seat));
    $('current-speaker').hidden = speakers.length === 0;
    $('current-speaker').textContent = speakers.length ? t('currentSpeaker', { name: speakers.join(' · ') }) : '';
    renderSeats(players);
    renderEvents(snapshot?.events || []);
    syncSpeech(snapshot);
    renderDossier();
    renderVotes(snapshot?.events || []);
  }
  function fillSeatSelect(select, selected) {
    select.replaceChildren(...getPlayers().map((player) => {
      const option = node('option', '', `${String(player.seat).padStart(2, '0')} · ${player.name}`);
      option.value = String(player.seat); option.selected = Number(player.seat) === Number(selected);
      return option;
    }));
  }
  // BEGIN PUBLIC ELECTION MARKS
  function publicElectionMarks(events, players, finished = false) {
    let original = new Set(), current = new Set(), withdrawn = new Set();
    const dead = new Set();
    let open = false, elected = null;
    const seats = (values) => new Set((Array.isArray(values) ? values : []).map(Number)
      .filter((seat) => Number.isInteger(seat) && seat >= 1 && seat <= 12));
    for (const event of events) {
      if (event.audience != null && event.audience !== 'public' && event.audience !== 'all') continue;
      if (event.kind === 'explosion' || event.kind === 'exile') dead.add(Number(event.seat));
      if (event.kind === 'dawn') for (const seat of seats(event.data?.deaths)) dead.add(seat);
      if (event.kind === 'hunter_shot') dead.add(Number(event.data?.target));
      if (event.kind === 'nominations') {
        original = seats(event.data?.candidates); current = new Set(original);
        withdrawn = new Set(); open = true; elected = null;
      } else if (event.kind === 'withdrawals' && open) {
        const remaining = seats(event.data?.candidates);
        for (const seat of current) if (!remaining.has(seat) && !dead.has(seat)) withdrawn.add(seat);
        current = remaining;
      } else if (event.kind === 'sheriff_ballots' && open) {
        const tally = Object.entries(event.data?.tally || {}).filter(([, votes]) => typeof votes === 'number' && votes > 0);
        const maximum = Math.max(0, ...tally.map(([, votes]) => votes));
        const leaders = tally.filter(([, votes]) => votes === maximum).map(([seat]) => Number(seat));
        if (leaders.length > 1) current = seats(leaders);
      } else if (event.kind === 'sheriff') {
        open = false; elected = Number(event.data?.sheriff) || null;
      }
    }
    const alive = new Set(players.filter((player) => player.alive).map((player) => Number(player.seat)));
    const marks = new Map();
    for (const seat of original) marks.set(seat, withdrawn.has(seat) ? 'withdrawn' : elected === seat ? 'elected'
      : open && !finished && current.has(seat) && alive.has(seat) ? 'candidate' : 'nominated');
    return marks;
  }
  // END PUBLIC ELECTION MARKS
  function renderSeats(players) {
    const acting = (state.snapshot?.current_speakers || []).map((seat) => Number(typeof seat === 'object' ? seat.seat : seat));
    const electionMarks = publicElectionMarks(state.snapshot?.events || [], players, Boolean(state.snapshot?.winner));
    const focusedSeat = $('seats').contains(document.activeElement) ? document.activeElement.dataset.seat : null;
    $('seats').replaceChildren(...[...players].sort((a, b) => a.seat - b.seat).map((player, index) => {
      const seat = node('button', 'seat'); seat.type = 'button';
      seat.dataset.seat = String(player.seat);
      seat.style.setProperty('--avatar-bg', avatarColors[index % avatarColors.length]);
      seat.classList.toggle('dead', !player.alive);
      seat.classList.toggle('active', acting.includes(Number(player.seat)));
      const readingIndex = speechPlayer.currentKey == null ? null : Number(String(speechPlayer.currentKey).split(':')[1]);
      seat.classList.toggle('audio-playing', readingIndex !== null && isSpeech(state.snapshot?.events?.[readingIndex] || {}) && Number(state.snapshot?.events?.[readingIndex]?.seat) === Number(player.seat));
      seat.classList.toggle('selected', $('details-dialog').open && state.detailsPanel === 'dossier' && Number(player.seat) === state.detailSeat);
      if (acting.includes(Number(player.seat))) seat.setAttribute('aria-current', 'true');
      seat.setAttribute('aria-label', `${t('inspect', { seat: player.seat })}: ${player.name}, ${roleName(permittedRole(player))}, ${t(player.alive ? 'alive' : 'eliminated')}`);
      seat.title = `${player.seat} · ${player.name}${acting.includes(Number(player.seat)) ? ` · ${t('speakingNow')}` : ''}`;
      const electionMark = electionMarks.get(Number(player.seat));
      if (electionMark) { seat.title += ` · ${t(electionMark)}`; seat.setAttribute('aria-label', `${seat.getAttribute('aria-label')}, ${t(electionMark)}`); }
      const wrap = node('span', 'avatar-wrap');
      wrap.append(node('span', 'avatar', [...String(player.name)][0] || '?'), node('span', 'seat-number', player.seat));
      if (acting.includes(Number(player.seat))) {
        const indicator = node('span', 'speaker-indicator'); indicator.setAttribute('aria-hidden', 'true');
        const bars = node('span', 'speaker-bars'); bars.append(node('i'), node('i'), node('i'));
        indicator.append(bars, node('span', '', t('speakingNow'))); seat.append(indicator);
      }
      if (player.sheriff) { const badge = node('span', 'sheriff-badge', '✦'); badge.title = t('sheriff'); wrap.append(badge); }
      const role = permittedRole(player);
      const roleLine = node('span', `seat-role ${role === 'wolf' ? 'wolf' : ''}`);
      roleLine.append(node('span', 'seat-role-text', player.alive ? roleName(role) : `${t('eliminated')} · ${roleName(role)}`));
      if (electionMark) roleLine.append(node('span', `election-tag ${electionMark}`, t(electionMark)));
      seat.append(wrap, node('span', 'seat-name', player.name), roleLine);
      seat.addEventListener('click', () => {
        state.detailSeat = Number(player.seat);
        if (state.mode === 'player' && state.followSeat !== Number(player.seat)) { state.followSeat = Number(player.seat); changePerspective(); }
        else render();
        state.drawerReturnSeat = Number(player.seat);
        openDetails('dossier');
      });
      return seat;
    }));
    if (focusedSeat) $('seats').querySelector(`[data-seat="${focusedSeat}"]`)?.focus({ preventScroll: true });
  }
  function isPrivate(event) {
    return event.audience !== undefined && event.audience !== null && event.audience !== 'public' && event.audience !== 'all';
  }
  function eventText(event) {
    if (typeof event.text === 'string') return event.text;
    if (event.text && typeof event.text === 'object') return event.text[state.snapshot?.language || 'en'] || event.text.en || event.text.zh || '';
    return phaseName(event.kind);
  }
  function renderEvents(events) {
    const signature = JSON.stringify([state.locale, state.mode, state.followSeat, state.at, events]);
    if (signature === state.lastEventSignature) return;
    state.lastEventSignature = signature;
    const transcript = $('transcript');
    const previousScroll = transcript.scrollTop;
    const children = [];
    let priorDay = null;
    for (const [index, event] of events.entries()) {
      if (event.day !== priorDay) {
        const label = node('div', 'phase-separator', `${t(phaseIsNight(event) ? 'night' : 'day')} ${event.day ?? 1}`);
        children.push(label); priorDay = event.day;
      }
      const speech = isSpeech(event);
      const item = node('article', `event ${speech ? '' : 'system'} ${isPrivate(event) ? 'private' : ''}`);
      const head = node('div', 'event-head');
      if (event.seat) head.append(node('span', 'event-seat', event.seat));
      head.append(node('span', 'event-speaker', speech ? playerName(event.seat) : t('referee')));
      if (isPrivate(event)) head.append(node('span', 'audience-tag', typeof event.audience === 'string' && event.audience.includes('wolf') ? t('wolfTeam') : t('private')));
      const meta = node('span', 'event-meta', phaseName(event.phase || event.kind));
      head.append(meta);
      if (isNarratable(event)) {
        const play = node('button', 'text-button speech-play', t('readSpeech')); play.type = 'button';
        const epoch = state.speechEpoch, language = speechLanguage(), key = speechKey(index);
        play.dataset.speechKey = key; play.dataset.speechSeat = String(event.seat || ''); play.dataset.speechReferee = String(!speech);
        play.addEventListener('click', () => {
          if (epoch !== state.speechEpoch || !play.isConnected) return;
          if (speechPlayer.currentKey === key) speechPlayer.stop();
          else if (speechPlayer.enable(language)) speechPlayer.play(eventText(event), language, key);
        }); head.append(play);
      }
      item.append(head, node('p', 'event-body', eventText(event)));
      children.push(item);
    }
    if (!children.length) {
      const empty = node('div', 'empty-state');
      empty.append(node('span', '', '◌'), node('h3', '', t('waitingTitle')), node('p', '', t('waitingCopy')));
      children.push(empty);
    }
    transcript.replaceChildren(...children);
    $('event-count').textContent = t('events', { count: events.length });
    if (state.autoScroll) transcript.scrollTop = transcript.scrollHeight;
    else transcript.scrollTop = previousScroll;
  }
  function renderDossier() {
    const player = playerFor(state.detailSeat);
    const target = $('dossier'); target.replaceChildren();
    if (!player) { target.append(node('p', 'ledger-empty', t('selectSeat'))); return; }
    const config = configFor(player.seat);
    const content = node('div', 'dossier-content');
    const avatar = node('div', 'avatar', [...String(player.name)][0] || '?');
    const body = node('div'); const heading = node('div', 'dossier-heading');
    heading.append(node('h3', '', `${String(player.seat).padStart(2, '0')} · ${player.name}`), node('span', 'dossier-role', roleName(permittedRole(player))));
    body.append(heading);
    body.append(node('p', 'dossier-config', config ? `${config.provider === 'demo' ? t('demoProvider') : config.provider} · ${config.model || '—'} · ${t(config.interaction_mode === 'tools' ? 'toolHarness' : 'jsonAction')}${player.sheriff ? ` · ${t('sheriff')}` : ''}` : t('noConfig')));
    if (config?.personality) body.append(node('p', 'dossier-personality', config.personality));
    content.append(avatar, body);
    const privateNotes = node('div', 'private-notes'); privateNotes.append(node('h4', '', t('notes')));
    let notes = '';
    const allowed = state.mode === 'omniscient' || (state.mode === 'player' && state.detailSeat === state.followSeat);
    if (allowed) {
      const snapshot = state.snapshot || {};
      const raw = snapshot.notes ?? snapshot.private_notes;
      if (typeof raw === 'string' && state.mode === 'player') notes = raw;
      else if (raw && typeof raw === 'object') notes = raw[player.seat] || '';
      if (!notes && state.mode === 'player') notes = snapshot.observation?.notes || snapshot.observation?.private_notes || '';
      if (typeof notes !== 'string') notes = JSON.stringify(notes);
    }
    privateNotes.append(node('p', '', notes || t('noNotes')), node('small', '', t('notesDisclaimer')));
    content.append(privateNotes); target.append(content);
  }
  function renderVotes(events) {
    const target = $('vote-ledger'); target.replaceChildren();
    const votes = events.filter((event) => !isPrivate(event) && /vote|ballot|tally|election_result/.test(event.kind));
    if (!votes.length) { target.append(node('p', 'ledger-empty', t('noVotes'))); return; }
    for (const event of votes.slice(-6).reverse()) {
      const entry = node('article', 'vote-entry');
      entry.append(node('h3', '', t('voteTitle', { day: event.day || 1, kind: phaseName(event.phase || event.kind) })));
      const data = event.data?.votes ?? event.data?.ballots;
      if (data && typeof data === 'object') {
        const pills = node('div', 'vote-pills');
        const ballots = Array.isArray(data) ? data.map((ballot) => [ballot.seat ?? ballot.voter, ballot.target ?? ballot.vote ?? null]) : Object.entries(data);
        for (const [voter, raw] of ballots) {
          const choice = typeof raw === 'object' && raw !== null ? raw.target : raw;
          pills.append(node('span', 'vote-pill', `${voter} → ${choice === null || choice === undefined ? t('abstain') : choice}`));
        }
        entry.append(pills);
      }
      entry.append(node('p', 'vote-outcome', eventText(event) || t('noData'))); target.append(entry);
    }
  }

  function freshDraft(language) {
    return names[language].map((name, i) => ({ seat: i + 1, name, provider: 'demo', model: 'scripted-v1', personality: personalities[language][i], temperature: 0.7, max_tokens: 500, thinking: null, reasoning_effort: null, interaction_mode: 'json' }));
  }
  function flashConfig(config) {
    return { ...config, provider: 'deepseek', model: 'deepseek-flash', thinking: 'disabled', reasoning_effort: null, temperature: 0.7, max_tokens: 8192, interaction_mode: 'tools' };
  }
  function flashHighConfig(config) {
    return { ...flashConfig(config), thinking: 'enabled', reasoning_effort: 'high', temperature: null, max_tokens: 32768 };
  }
  function renderProviderSetup() {
    const configured = state.providerInfo?.deepseek?.configured;
    const keyStatus = $('deepseek-key-status');
    keyStatus.textContent = t(state.providerLoading ? 'keyChecking' : configured === true ? 'keyConfigured' : configured === false ? 'keyMissing' : 'keyUnknown');
    keyStatus.classList.toggle('configured', configured === true);
    $('deepseek-check').disabled = state.connectionChecking || state.providerLoading || configured !== true;
    $('deepseek-check').textContent = t(state.connectionChecking ? 'testConnectionBusy' : 'testConnection');
    $('deepseek-check').title = t('connectionCost');
    const result = $('deepseek-check-result');
    result.hidden = !state.connectionChecking && !state.connectionResult && !state.flashApplied;
    result.classList.toggle('failed', state.connectionResult?.ok === false);
    if (state.connectionChecking) result.textContent = t('connectionChecking');
    else if (state.connectionResult) result.textContent = [t(state.connectionResult.ok ? 'connectionSuccess' : 'connectionFailure'), state.connectionResult.message].filter(Boolean).join(' ');
    else if (state.flashApplied) result.textContent = t('flashApplied');
  }
  async function refreshProviderSetup() {
    state.providerLoading = true; renderProviderSetup();
    try { state.providerInfo = await api('/api/providers'); }
    catch (_) { state.providerInfo = null; }
    finally { state.providerLoading = false; renderProviderSetup(); }
  }
  async function checkDeepSeek() {
    if (state.connectionChecking || state.providerInfo?.deepseek?.configured !== true) return;
    state.connectionChecking = true; state.connectionResult = null; state.flashApplied = false; renderProviderSetup();
    try {
      const response = await api('/api/providers/deepseek/check', { language: $('setup-language').value });
      const message = [response.message, response.reply, response.text].find((value) => typeof value === 'string');
      state.connectionResult = { ok: response.ok !== false && response.success !== false, message: message || '' };
    } catch (error) { state.connectionResult = { ok: false, message: error.message }; }
    finally { state.connectionChecking = false; renderProviderSetup(); }
  }
  function renderSetup() {
    renderProviderSetup();
    const container = $('setup-players'); container.replaceChildren();
    state.draft.forEach((config, index) => {
      const row = node('div', 'player-config'); row.append(node('span', 'config-number', String(index + 1).padStart(2, '0')));
      const name = node('input'); name.value = config.name; name.maxLength = 50; name.required = true;
      name.setAttribute('aria-label', `${t('seat', { seat: index + 1 })} ${t('playerName')}`);
      name.addEventListener('input', () => { config.name = name.value; }); row.append(name);
      const provider = node('select'); provider.setAttribute('aria-label', `${t('seat', { seat: index + 1 })} provider`);
      for (const [value, label] of [['demo', t('demoProvider')], ['deepseek', 'DeepSeek API'], ['openai', 'OpenAI API'], ['openai_subscription', 'ChatGPT plan']]) {
        const option = node('option', '', label); option.value = value; option.selected = config.provider === value; provider.append(option);
      }
      provider.addEventListener('change', () => {
        if (provider.value === 'deepseek') Object.assign(config, flashConfig(config));
        else {
          config.provider = provider.value;
          config.model = provider.value === 'demo' ? 'scripted-v1' : '';
          config.temperature = provider.value === 'openai_subscription' ? null : 0.7;
          config.max_tokens = provider.value === 'openai_subscription' ? null : 500;
          config.thinking = null; config.reasoning_effort = null;
          config.interaction_mode = 'json';
        }
        renderSetup();
      }); row.append(provider);
      const model = node('input', 'config-model'); model.value = config.model || ''; model.placeholder = t('modelId'); model.required = true; model.maxLength = 120;
      model.setAttribute('aria-label', `${t('seat', { seat: index + 1 })} ${t('modelId')}`);
      model.addEventListener('input', () => { config.model = model.value; }); row.append(model);
      const personality = node('input', 'personality-input'); personality.value = config.personality || ''; personality.placeholder = t('personality'); personality.maxLength = 2000;
      personality.setAttribute('aria-label', `${t('seat', { seat: index + 1 })} ${t('personality')}`);
      personality.addEventListener('input', () => { config.personality = personality.value; }); row.append(personality);
      const budgets = node('div', 'budget-row');
      const modeLabel = node('label', '', `${t('interactionMode')} `); const mode = node('select');
      mode.setAttribute('aria-label', `${t('seat', { seat: index + 1 })} ${t('interactionMode')}`);
      for (const [value, label] of [['json', t('jsonAction')], ['tools', t('toolHarness')]]) {
        const option = node('option', '', label); option.value = value;
        option.selected = value === (config.interaction_mode || 'json');
        option.disabled = value === 'tools' && config.provider !== 'deepseek'; mode.append(option);
      }
      mode.addEventListener('change', () => {
        config.interaction_mode = mode.value;
        renderSetup();
      }); modeLabel.append(mode);
      const modeRow = node('div', 'budget-row thinking-row'); modeRow.append(modeLabel); row.append(modeRow);
      if (config.provider === 'deepseek') {
        const thinkingLabel = node('label', '', `${t('thinking')} `); const thinking = node('select');
        for (const [value, label] of [['', t('modelDefault')], ['enabled', t('thinkingEnabled')], ['disabled', t('thinkingDisabled')]]) {
          const option = node('option', '', label); option.value = value; option.selected = value === (config.thinking || ''); thinking.append(option);
        }
        thinking.addEventListener('change', () => {
          config.thinking = thinking.value || null;
          if (config.thinking === 'enabled') { config.temperature = null; config.reasoning_effort = config.reasoning_effort || 'high'; config.max_tokens = Math.max(config.max_tokens || 0, 32768); }
          else config.reasoning_effort = null;
          renderSetup();
        }); thinkingLabel.append(thinking);
        const effortLabel = node('label', '', `${t('reasoningEffort')} `); const effort = node('select'); effort.disabled = config.thinking !== 'enabled';
        for (const [value, label] of [['', t('modelDefault')], ['low', t('effortLow')], ['high', t('effortHigh')], ['max', t('effortMax')]]) {
          const option = node('option', '', label); option.value = value; option.selected = value === (config.reasoning_effort || ''); effort.append(option);
        }
        effort.addEventListener('change', () => { config.reasoning_effort = effort.value || null; }); effortLabel.append(effort);
        const thinkingRow = node('div', 'budget-row thinking-row'); thinkingRow.append(thinkingLabel, effortLabel); row.append(thinkingRow);
      }
      if (config.provider === 'openai_subscription') budgets.append(node('span', '', t('subscriptionBudget')));
      else {
        const providerDefault = state.locale === 'zh' ? '留空使用模型默认值' : 'Blank uses model default';
        const tempLabel = node('label', '', `${t('temperature')} `); const temp = node('input'); temp.type = 'number'; temp.min = '0'; temp.max = '2'; temp.step = '.1'; temp.value = config.temperature ?? ''; temp.placeholder = providerDefault; temp.title = providerDefault;
        if (config.provider === 'deepseek' && config.thinking === 'enabled') { config.temperature = null; temp.value = ''; temp.disabled = true; temp.title = t('temperatureThinking'); }
        temp.addEventListener('input', () => { config.temperature = temp.value === '' ? null : Number(temp.value); }); tempLabel.append(temp);
        const tokenLabel = node('label', '', `${t('tokens')} `); const tokens = node('input'); tokens.type = 'number'; tokens.min = '128'; tokens.max = '32768'; tokens.step = '1'; tokens.value = config.max_tokens ?? ''; tokens.placeholder = providerDefault; tokens.title = providerDefault;
        tokens.addEventListener('input', () => { config.max_tokens = tokens.value === '' ? null : Number(tokens.value); }); tokenLabel.append(tokens);
        budgets.append(tempLabel, tokenLabel);
      }
      row.append(budgets); container.append(row);
    });
  }
  function openDialog(id) { $(id).showModal(); document.body.classList.add('dialog-open'); }
  function closeDialog(id) { $(id).close(); document.body.classList.remove('dialog-open'); }
  function setDetailsPanel(panel) {
    state.detailsPanel = panel;
    const dossier = panel === 'dossier';
    $('details-title').textContent = t(dossier ? 'playerDetail' : 'voteLedger');
    $('dossier-panel').hidden = !dossier; $('ledger-panel').hidden = dossier;
    for (const [id, selected] of [['dossier-tab', dossier], ['votes-tab', !dossier]]) {
      $(id).setAttribute('aria-selected', String(selected)); $(id).tabIndex = selected ? 0 : -1;
    }
  }
  function openDetails(panel) {
    setDetailsPanel(panel);
    if (!$('details-dialog').open) openDialog('details-dialog');
    renderSeats(getPlayers());
  }
  function openSetup() {
    const language = state.snapshot?.language || state.locale;
    $('setup-language').value = language;
    const configs = state.snapshot?.configs;
    state.draft = Array.isArray(configs) && configs.length === 12 ? configs.map((config) => ({ thinking: null, reasoning_effort: null, interaction_mode: 'json', ...config })) : freshDraft(language);
    state.flashApplied = false;
    $('setup-error').hidden = true; renderSetup(); openDialog('setup-dialog'); refreshProviderSetup();
  }
  async function createGame(event) {
    event.preventDefault(); if (state.busy) return;
    if (state.draft.some((config) => !config.name.trim() || !config.model.trim())) {
      $('setup-error').textContent = t('invalidPlayers'); $('setup-error').hidden = false; return;
    }
    state.busy = true; $('setup-create').disabled = true;
    try {
      const language = $('setup-language').value;
      const players = state.draft.map((config) => ({ ...config, name: config.name.trim(), model: config.model.trim(), language }));
      await api('/api/game', { seed: Number($('setup-seed').value), language, players });
      resetSpeechView(); state.at = null; state.lastEventSignature = ''; closeDialog('setup-dialog');
      await refresh(); notice(t('gameReplaced'));
    } catch (error) { $('setup-error').textContent = error.message; $('setup-error').hidden = false; }
    finally { state.busy = false; $('setup-create').disabled = false; renderControls(); }
  }

  $('dossier-open').addEventListener('click', () => { state.drawerReturnSeat = null; openDetails('dossier'); });
  $('votes-open').addEventListener('click', () => { state.drawerReturnSeat = null; openDetails('votes'); });
  $('details-close').addEventListener('click', () => closeDialog('details-dialog'));
  for (const panel of ['dossier', 'votes']) {
    $(`${panel}-tab`).addEventListener('click', () => { setDetailsPanel(panel); renderSeats(getPlayers()); });
    $(`${panel}-tab`).addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 'dossier' : event.key === 'End' ? 'votes' : panel === 'dossier' ? 'votes' : 'dossier';
      setDetailsPanel(next); $(`${next}-tab`).focus(); renderSeats(getPlayers());
    });
  }
  $('details-dialog').addEventListener('click', (event) => {
    if (event.target !== $('details-dialog')) return;
    const bounds = event.target.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeDialog('details-dialog');
  });
  $('details-dialog').addEventListener('close', () => {
    renderSeats(getPlayers());
    if (state.drawerReturnSeat) $('seats').querySelector(`[data-seat="${state.drawerReturnSeat}"]`)?.focus({ preventScroll: true });
  });
  $('locale-en').addEventListener('click', () => setLocale('en'));
  $('locale-zh').addEventListener('click', () => setLocale('zh'));
  $('play').addEventListener('click', () => command(state.snapshot?.status === 'running' ? '/api/pause' : '/api/play'));
  $('step').addEventListener('click', () => command('/api/step'));
  $('perspective').addEventListener('change', (event) => { state.mode = event.target.value; if (state.mode === 'player') state.detailSeat = state.followSeat; state.lastEventSignature = ''; changePerspective(); });
  $('follow-seat').addEventListener('change', (event) => { state.followSeat = Number(event.target.value); state.detailSeat = state.followSeat; changePerspective(); });
  $('detail-seat').addEventListener('change', (event) => { state.detailSeat = Number(event.target.value); renderDossier(); renderSeats(getPlayers()); });
  $('speech-toggle').addEventListener('click', () => {
    if (state.autoSpeech) { state.autoSpeech = false; speechPlayer.disable(); }
    else if (speechPlayer.enable(speechLanguage())) { state.autoSpeech = true; renderSpeechControls(); }
  });
  window.addEventListener('pagehide', () => speechPlayer.disable());
  $('autoscroll').addEventListener('click', () => { state.autoScroll = !state.autoScroll; renderControls(); if (state.autoScroll) $('transcript').scrollTop = $('transcript').scrollHeight; });
  $('replay-range').addEventListener('input', (event) => { state.at = Number(event.target.value); changePerspective(); });
  $('replay-back').addEventListener('click', () => { state.at = Math.max(0, (state.at ?? state.snapshot?.step ?? 0) - 1); changePerspective(); });
  $('go-live').addEventListener('click', () => { state.at = null; changePerspective(); });
  $('setup-open').addEventListener('click', openSetup);
  $('setup-close').addEventListener('click', () => closeDialog('setup-dialog'));
  $('setup-cancel').addEventListener('click', () => closeDialog('setup-dialog'));
  $('setup-language').addEventListener('change', () => {
    const language = $('setup-language').value;
    state.draft.forEach((config, index) => {
      if ([names.en[index], names.zh[index]].includes(config.name)) config.name = names[language][index];
      if ([personalities.en[index], personalities.zh[index]].includes(config.personality)) config.personality = personalities[language][index];
    }); renderSetup();
  });
  $('setup-form').addEventListener('submit', createGame);
  $('deepseek-preset').addEventListener('click', () => {
    state.draft = state.draft.map(flashConfig); state.flashApplied = true; state.connectionResult = null; renderSetup();
  });
  $('deepseek-high-preset').addEventListener('click', () => {
    state.draft = state.draft.map(flashHighConfig); state.flashApplied = true; state.connectionResult = null; renderSetup();
  });
  $('deepseek-check').addEventListener('click', checkDeepSeek);
  $('export').addEventListener('click', () => openDialog('export-dialog'));
  $('export-close').addEventListener('click', () => closeDialog('export-dialog'));
  $('export-cancel').addEventListener('click', () => closeDialog('export-dialog'));
  $('export-download').addEventListener('click', async () => {
    $('export-download').disabled = true;
    try {
      const archive = await api('/api/export');
      const url = URL.createObjectURL(new Blob([JSON.stringify(archive, null, 2)], { type: 'application/json' }));
      const link = node('a'); link.href = url; link.download = `werewolf-${new Date().toISOString().replaceAll(':', '-')}.json`;
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      closeDialog('export-dialog');
    } catch (error) { notice(error.message || t('archiveFailed'), true); closeDialog('export-dialog'); }
    finally { $('export-download').disabled = false; }
  });
  document.querySelectorAll('dialog').forEach((dialog) => {
    dialog.addEventListener('close', () => document.body.classList.remove('dialog-open'));
  });

  setLocale(state.locale);
  refresh();
  // Polling fetches spectator projections only; it never drives inference.
  setInterval(() => { if (!state.busy && !$('setup-dialog').open) refresh(); }, 1200);
})();
