import {
  AccessToken,
  AgentDispatchClient,
  RoomServiceClient,
} from "livekit-server-sdk";
import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME, verifySessionToken } from "@/lib/auth/session";
import { logSsoTransaction } from "@/lib/sso/soap";

export const runtime = "nodejs";

// Must match `agent_name` in agent.py, which is what registers under it. A
// mismatch is silent: LiveKit creates a dispatch no worker serves, so the agent
// simply never joins. Defaults to "nongaree-agent" so an environment that sets
// nothing behaves exactly as before.
const AGENT_NAME = process.env.AGENT_NAME || "nongaree-agent";
const AGENT_PARTICIPANT_KIND = 4;
const recentlyResetRooms = new Map<string, number>();
const dispatchLocks = new Map<string, Promise<void>>();

export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl;
  const session = await verifySessionToken(req.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (!session) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }
  const shouldResetOnThisRequest =
    process.env.LIVEKIT_RESET_ROOM_ON_TOKEN === "true" && searchParams.get("reset") === "true";

  // Each authenticated user gets their own room so audio, transcripts, and
  // answers stay private. The room is derived server-side from the session —
  // the client cannot request another user's room. (Sanitize defensively; RD
  // SSO usernames are normally alphanumeric.)
  const safeUser = session.username.replace(/[^a-zA-Z0-9_-]/g, "_");
  const roomName = `nongaree-${safeUser}`;
  const identity = session.username;

  if (session.tokenId) {
    void logSsoTransaction(session.username, session.tokenId, "Load").catch((error) => {
      console.error("[SSO] Failed to record LiveKit token transaction", error);
    });
  }

  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;
  const livekitUrl = process.env.LIVEKIT_URL;

  if (!apiKey || !apiSecret || !livekitUrl) {
    return NextResponse.json(
      { error: "LiveKit credentials not configured" },
      { status: 500 }
    );
  }

  const httpUrl = livekitUrl.replace(/^ws/, "http");
  const roomService = new RoomServiceClient(httpUrl, apiKey, apiSecret);
  let roomWasReset = false;
  if (shouldResetOnThisRequest) {
    const now = Date.now();
    const lastReset = recentlyResetRooms.get(roomName) || 0;
    const shouldResetRoom = now - lastReset > 10_000;
    if (shouldResetRoom) {
      recentlyResetRooms.set(roomName, now);
      try {
        await roomService.deleteRoom(roomName);
        console.log(`Successfully deleted/reset room: ${roomName}`);
      } catch (err: unknown) {
        const errorMsg = String(err);
        const hasStatus = err && typeof err === "object" && "status" in err;
        const hasCode = err && typeof err === "object" && "code" in err;
        const status = hasStatus ? (err as Record<string, unknown>).status : undefined;
        const code = hasCode ? (err as Record<string, unknown>).code : undefined;
        if (status === 404 || code === "not_found" || errorMsg.includes("does not exist")) {
          console.log(`Room ${roomName} did not exist, skipping deletion.`);
        } else {
          console.log(`Failed to delete room ${roomName}:`, err);
        }
      }
      try {
        await roomService.createRoom({ name: roomName });
        roomWasReset = true;
        console.log(`Successfully created fresh room: ${roomName}`);
      } catch (err: unknown) {
        console.log(`Failed to create fresh room ${roomName}:`, err);
      }
    } else {
      try {
        await roomService.createRoom({ name: roomName });
      } catch (err: unknown) {
        const errorMsg = String(err);
        if (!errorMsg.includes("already exists")) {
          console.log(`Room ${roomName} create check failed:`, err);
        }
      }
      console.log(`Room ${roomName} was reset recently; reusing current fresh room.`);
    }
  }

  async function listExistingDispatches(agentService: AgentDispatchClient) {
    try {
      return await agentService.listDispatch(roomName);
    } catch (err: unknown) {
      const errorMsg = String(err);
      const hasStatus = err && typeof err === "object" && "status" in err;
      const status = hasStatus ? (err as Record<string, unknown>).status : undefined;
      // "The room does not exist yet" is reported DIFFERENTLY by LiveKit Cloud and by
      // a self-hosted server, and only the Cloud shape was handled:
      //   Cloud      -> 404
      //   self-hosted-> 503 "twirp error unknown: no response from servers"
      // Verified against the RD server: ListDispatch on an existing room returns 200,
      // on a missing room 503. Rethrowing the 503 killed dispatch entirely, so the
      // agent never joined and every question was silently dropped.
      const roomMissing =
        status === 404 ||
        status === 503 ||
        errorMsg.includes("does not exist") ||
        errorMsg.includes("no response from servers");
      if (roomMissing) {
        await roomService.createRoom({ name: roomName }).catch(() => {});
        return [];
      } else {
        throw err;
      }
    }
  }

  async function removeDuplicateDispatches(agentService: AgentDispatchClient) {
    const dispatches = await listExistingDispatches(agentService);
    const activeDispatches = dispatches
      .filter((dispatch) => (
        dispatch.agentName === AGENT_NAME &&
        (dispatch.state?.jobs?.length || 0) > 0
      ))
      .sort((a, b) => a.id.localeCompare(b.id));
    const staleDispatches = dispatches.filter((dispatch) => (
      dispatch.agentName !== AGENT_NAME ||
      (dispatch.state?.jobs?.length || 0) === 0
    ));
    const [existing, ...duplicates] = activeDispatches;
    await Promise.all(
      [...duplicates, ...staleDispatches].map((dispatch) =>
        agentService.deleteDispatch(dispatch.id, roomName).catch((err) => {
          console.log(`Failed to delete stale/duplicate agent dispatch ${dispatch.id}:`, err);
        }),
      ),
    );
    return existing;
  }

  async function clearRoomDispatches(agentService: AgentDispatchClient) {
    const dispatches = await listExistingDispatches(agentService);
    await Promise.all(
      dispatches.map((dispatch) =>
        agentService.deleteDispatch(dispatch.id, roomName).catch((err) => {
          console.log(`Failed to delete stale agent dispatch ${dispatch.id}:`, err);
        }),
      ),
    );
  }

  async function ensureSingleAgentParticipant() {
    try {
      const participants = await roomService.listParticipants(roomName);
      const agentParticipants = participants
        .filter((participant) => (
          participant.kind === AGENT_PARTICIPANT_KIND ||
          participant.name === AGENT_NAME ||
          participant.identity.includes(AGENT_NAME)
        ))
        .sort((a, b) => {
          const aJoined = Number(a.joinedAtMs || 0);
          const bJoined = Number(b.joinedAtMs || 0);
          if (aJoined !== bJoined) return aJoined - bJoined;
          return a.identity.localeCompare(b.identity);
        });

      const [existing, ...duplicates] = agentParticipants;
      await Promise.all(
        duplicates.map((participant) =>
          roomService.removeParticipant(roomName, participant.identity).catch((err) => {
            console.log(`Failed to remove duplicate agent participant ${participant.identity}:`, err);
          }),
        ),
      );

      if (existing) {
        console.log(`Agent participant already connected for room ${roomName}:`, existing.identity);
        return existing;
      }
    } catch (err: unknown) {
      const errorMsg = String(err);
      const hasStatus = err && typeof err === "object" && "status" in err;
      const status = hasStatus ? (err as Record<string, unknown>).status : undefined;
      if (status === 404 || errorMsg.includes("does not exist")) {
        await roomService.createRoom({ name: roomName }).catch(() => {});
        return undefined;
      }
      console.log(`Failed to inspect agent participants for room ${roomName}:`, err);
    }
    return undefined;
  }

  // Explicitly dispatch the agent worker once. Token fetches can happen more
  // than once during dev refresh/StrictMode, so serialize by room and avoid
  // stacking multiple bots when two token requests race.
  const previousDispatch = dispatchLocks.get(roomName) ?? Promise.resolve();
  const dispatchLock = previousDispatch
    .catch(() => {})
    .then(async () => {
      try {
        const agentService = new AgentDispatchClient(httpUrl, apiKey, apiSecret);
        const existingParticipant = roomWasReset ? undefined : await ensureSingleAgentParticipant();
        if (existingParticipant) {
          console.log(`Skipping agent dispatch because an agent is already connected in room ${roomName}`);
          // Only safe on THIS branch: nothing was created just now, so any dispatch
          // sitting here with no jobs really is stale.
          await new Promise((resolve) => setTimeout(resolve, 100));
          await removeDuplicateDispatches(agentService);
        } else {
          await clearRoomDispatches(agentService);
          const dispatch = await agentService.createDispatch(roomName, AGENT_NAME);
          console.log(`Successfully created agent dispatch for room ${roomName}:`, dispatch.id);
          // Deliberately NO removeDuplicateDispatches() here.
          //
          // clearRoomDispatches() ran immediately above, so a duplicate is impossible
          // by construction. Worse, removeDuplicateDispatches() treats any dispatch
          // with `jobs.length === 0` as stale — and a dispatch created 100ms ago
          // normally has no job assigned yet, so it deleted the dispatch it had just
          // created. LiveKit then had nothing to assign and the agent silently never
          // joined: no error, no log, just a room the bot never enters.
        }
        await ensureSingleAgentParticipant();
      } catch (err) {
        console.log(`Failed to create agent dispatch for room ${roomName}:`, err);
      }
    });
  dispatchLocks.set(roomName, dispatchLock);
  await dispatchLock;
  if (dispatchLocks.get(roomName) === dispatchLock) {
    dispatchLocks.delete(roomName);
  }

  const at = new AccessToken(apiKey, apiSecret, {
    identity,
    ttl: 3600,
  });

  at.addGrant({
    roomJoin: true,
    room: roomName,
    canPublish: true,
    canSubscribe: true,
    canPublishData: true,
  });

  const token = await at.toJwt();

  return NextResponse.json({ token, url: livekitUrl });
}
