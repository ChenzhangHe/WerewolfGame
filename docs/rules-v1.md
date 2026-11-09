# Twelve-player rules: rules-v1

Status: initial simulator rules profile. The lineup and core flow follow the
Chinese standard 预女猎白. Variant-sensitive choices below are explicit simulator
conventions, not claims that every app or competition uses identical rules.
Freeze this profile before a game; changes require a new ruleset version.

## Setup and public knowledge

Assign seats 1–12 around a circle. Seats, circular order, role counts, and all
rules are public. Assigned roles are secret: each player knows their own role,
and Wolves learn their teammates at the first wolf phase. This interprets
"positions are known" as public seats and lineup, not public role assignments.

| Role | Count | Team |
| --- | --- | --- |
| Wolf 狼人 | 4 | Wolves |
| Villager 平民 | 4 | Good |
| Seer 预言家 | 1 | Good; special role |
| Witch 女巫 | 1 | Good; special role |
| Hunter 猎人 | 1 | Good; special role |
| Idiot / Fool 白痴／愚者 | 1 | Good; special role |

Sheriff 警长 is an elected office held in addition to a player's secret role.
Start with night 1. There is no preliminary public discussion.

## Disclosure

Death and exile do not automatically reveal role or faction. Dawn announces
eliminated seats, without cause, in ascending seat order; ordering does not encode
the attack or potion sequence. Announce a peaceful night if nobody died.

Role claims are unverified speech. Actual Idiot reveal, Wolf self-explosion,
and Hunter shooting are public ability events. Other hidden assignments remain
secret until the postgame role reveal. Dead players stop receiving new private
results or participating after their permitted last words and death abilities.

## Night actions

Use the fixed phase order Wolves, Witch, Seer, Hunter status, dawn. First-night
passive-role confirmation is private and does not expose assignments. Do not
publicly skip phases because a role is absent, dead, or out of resources.

- Wolves privately coordinate and submit one attack on a living seat, including
  a teammate or themselves, or choose no attack. The AI coordination protocol
  must have a fixed budget and deterministic disagreement handling; its exact
  implementation remains to be specified before playable code is complete.
- Witch starts with one antidote and one poison for the entire game and may use
  at most one potion each night. Antidote saves the current wolf attack target;
  poison targets one living seat. Witch cannot save herself on any night. While
  antidote remains, she receives the wolf target or no-attack result. After it is
  spent, subsequent wolf targets are not supplied, even if she is attacked.
- Seer may investigate one other living seat per night, receiving only Wolf or
  Good. Good does not identify a specific role. Repeated investigations are legal.
- Hunter privately receives shooting eligibility. Poison disables the death shot,
  including when Hunter is both attacked and poisoned that night.
- Villagers and Idiot have no chosen night action.

Collect night actions before announcing deaths. A player alive at the start of
the night may act despite being targeted that night. Seer results are private;
Wolves do not learn whether a save succeeded until public information supports it.

## Sheriff election

On day 1, hold the election before announcing night deaths. Pending night victims
participate; do not remove them from ballots or otherwise disclose their status.

1. All seats simultaneously choose whether to run. Publish the candidate list.
2. Candidates speak in ascending seat order, using the fixed speech allowance.
3. Candidates simultaneously choose whether to withdraw; publish withdrawals.
4. Only players who originally declined to run may vote. Withdrawn candidates
   do not acquire voting rights. Voting is simultaneous; abstention is allowed.
5. A sole remaining candidate is elected automatically. No candidates means no
   Sheriff. With multiple candidates and no eligible voters or no votes, no
   Sheriff is elected.
6. Highest vote count wins. Tied leaders speak once more in reverse of their
   prior speaking order, then original eligible voters vote among them. A second
   tie means no Sheriff for this game.

Sheriff has a 1.5-weight exile vote, chooses the permitted discussion direction,
and speaks last. Election votes always have weight 1. Recommendations do not
bind other voters. On elimination, Sheriff may transfer the badge to one eligible
living player or destroy it; destruction means no later election. Resolve a
pending victim's badge after announcing deaths; never transfer to another player
being eliminated in the same announcement.

## Ordinary daytime discussion and exile

After the election on day 1, and at dawn on later days, announce deaths, resolve
death abilities and badge handling, then applicable last words before discussion.

- If exactly one player died overnight, Sheriff selects clockwise or
  counterclockwise starting beside that dead seat. Otherwise start beside Sheriff.
- All living players speak once in the selected circular order; move Sheriff's
  speaking turn to the end without changing the relative order of other seats.
- Without Sheriff, the referee selects a starting living seat and direction
  using seeded randomness independent of hidden assignments, and announces them.
- Speech is turn-based, with a fixed text allowance set before play. No ordinary
  interruptions, extra response round, private daytime chat, or changing budgets.
- After speeches, eligible living voters simultaneously vote for one eligible
  living seat or abstain. Self-voting is legal. Publish each vote and the tally
  only after ballots lock. Sheriff weight is 1.5; others have weight 1.
- Highest positive total is exiled. If tied, tied candidates speak in the existing
  discussion order, then eligible voters other than the tied candidates vote
  among them. A second tie, or no positive votes, means no exile.
- Resolve exile and abilities, applicable badge handling and last words, then
  enter the next night unless the game has ended.

## Hunter, Idiot, and last words

Hunter killed by wolf attack or exile may shoot one living player or decline.
Poison prevents shooting. Shooting publicly identifies the actor and target.
The target dies without an ordinary role reveal. Resolve a permitted shot before
last words, subject to the wolf-attack-first victory rule below.

Idiot automatically reveals on first exile and stays alive, retaining normal
speaking turns but permanently losing voting rights and eligibility for exile.
If Sheriff, transfer or destroy the badge. The day ends after the reveal and its
final speech. Revealed Idiot cannot receive the badge later. Wolf attack, poison,
and Hunter shot kill Idiot normally, without this protection. A revealed living
Idiot still counts as a living special role for victory.

First-night victims and ordinary daytime exile victims have one last speech.
Later night victims have none. For this profile, a Hunter-shot victim inherits
the originating death's night/day classification for last words. Self-exploding
Wolves have no last words. Last words do not grant further votes or ordinary
actions and never contain automatic referee confirmation of claims.

## Wolf self-explosion

Use double self-explosion for Sheriff interruption, 双爆吞警徽. A Wolf may reveal
and eliminate itself during campaign or ordinary discussion, ending the day
without exile after required death and badge resolution.

For the simulator, offer a simultaneous private explode/pass decision to every
eligible Wolf before each speech and before the election vote, including resumed
election voting. If several choose explosion, the lowest seat acts and the other
choices have no effect. This is an explicit discrete adaptation of live-table
interruptions and must not depend on provider speed.

- First explosion during the election preserves the remaining candidate state.
  Announce pending deaths and resolve required abilities, badge handling, and
  eligible first-night last words before entering night.
- Next day resumes with withdrawals and voting, without repeating ordinary
  campaign speeches. Tied candidates may still give runoff speeches.
- A second explosion during the unfinished election destroys the badge for the
  game and again ends the day after required resolution.
- A pending poisoned Wolf may explode before deaths are announced. Count that
  seat only once as dead; the poison remains spent and does not acquire a new
  target. This profile lets the explosion interrupt the day despite that poison.
- Explosion after a Sheriff is elected does not automatically destroy the badge.
  If the exploding Wolf holds it, use normal transfer/destruction rules.
- No explosions during ballots, death resolution, or last words. After discussion
  ends and voting begins, the interruption window is closed.

## Victory and resolution precedence

Good wins when all four Wolves are eliminated. Wolves win when either all four
ordinary Villagers or all four special roles are eliminated. Numeric parity alone
does not end the game. Eliminated teammates share their team's eventual outcome.

Use wolf-attack-first resolution, 狼刀在先:

1. Apply antidote to the wolf attack, then resolve any unsaved attack.
2. If that attack completes a Wolf victory, end immediately, before poison or a
   Hunter shot can reverse the outcome.
3. Otherwise resolve poison and any permitted Hunter shot. Poison disables Hunter
   shooting before a shot is offered, even if the same Hunter was attacked.
4. Check victory after each subsequent elimination or ability resolution and stop
   when a team wins. Within a batch of night effects, wolf attack precedes poison.

Evaluate these rules on authoritative state without exposing intermediate death
information to players. Day 1's pending victims can participate in the election
unless a terminal outcome has already ended the game. Endgame reveals all roles.

## Sources and scope

Sources establish the standard lineup and common conventions; the explicit
tie handling, ordering, and discrete AI action windows above remove ambiguity
for this simulator. They are not a verbatim implementation of any single app.

- [Official tournament lineup](https://langrensha.com/20240319/31014_1144073.html).
- [Official-account standard-game guide: hidden roles and double explosion](https://www.sohu.com/a/311842022_100077559).
- [Standard-app description: no death reveals, Witch restrictions, Idiot](https://www.9game.cn/langrensha/8653650.html).
- [Election timing, speaking, and last words](https://www.tgbus.com/news/166377).
- [Seer, Witch, Hunter, and common rule variations](https://m.jiemian.com/article/6119334.html).
- [Witch loses attack information after antidote use](https://www.langrensha.net/strategy/2021090301.html).
- [Idiot's protection and its limits](https://www.langrensha.net/strategy/2023010602.html).
- [Double-explosion election variants](https://www.langrensha.net/strategy/2021060701.html).
- [Wolf-attack-first victory and other resolution conventions](https://www.langrensha.net/strategy/2021050801.html).

Before implementation is considered complete, turn every phase and interruption
above into state transitions and verify the edge cases with engine tests.
