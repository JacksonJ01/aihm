"use client";

import React from "react";
import Link from "next/link";
import { useState, useRef, useEffect, useLayoutEffect } from "react";
import { usePathname } from 'next/navigation';
import { createPortal } from "react-dom";

export default function NavBar() {
  const [programsOpen, setProgramsOpen] = useState(false);
  const [communityOpen, setCommunityOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const programsRef = useRef<HTMLDivElement | null>(null);
  const communityRef = useRef<HTMLDivElement | null>(null);
  const profileRef = useRef<HTMLDivElement | null>(null);
  const programsBtnRef = useRef<HTMLButtonElement | null>(null);
  const communityBtnRef = useRef<HTMLButtonElement | null>(null);
  const profileBtnRef = useRef<HTMLButtonElement | null>(null);
  const [isMobile, setIsMobile] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [programsMobileOpen, setProgramsMobileOpen] = useState(false);
  const [communityMobileOpen, setCommunityMobileOpen] = useState(false);
  const [profileMobileOpen, setProfileMobileOpen] = useState(false);
  const [activeMobileTop, setActiveMobileTop] = useState<string | null>(null);
  // Mobile toggles that close other dropdowns when opening
  const toggleProgramsMobile = () => {
    setProgramsMobileOpen(prev => {
      const next = !prev;
      if (next) {
        setCommunityMobileOpen(false);
        setProfileMobileOpen(false);
      }
      return next;
    });
  };
  const toggleCommunityMobile = () => {
    setCommunityMobileOpen(prev => {
      const next = !prev;
      if (next) {
        setProgramsMobileOpen(false);
        setProfileMobileOpen(false);
      }
      return next;
    });
  };
  const toggleProfileMobile = () => {
    setProfileMobileOpen(prev => {
      const next = !prev;
      if (next) {
        setProgramsMobileOpen(false);
        setCommunityMobileOpen(false);
      }
      return next;
    });
  };

  // keep activeMobileTop in sync so only one top item appears active (white) at a time
  const setActiveFor = (key: string | null) => {
    setActiveMobileTop(key);
  };

  // route-aware active styling
  const pathname = usePathname() || '/';
  const notRoot = pathname !== '/';
  const isActivePath = (p: string) => notRoot && pathname.startsWith(p);
  const isProgramsActive = notRoot && ['/programs', '/browsePrograms', '/progress'].some(p => pathname.startsWith(p));
  const startActive = isActivePath('/workouts');
  const communityActive = notRoot && ['/community', '/friends'].some(p => pathname.startsWith(p));
  const notificationsActive = isActivePath('/notifications');
  const profileActive = notRoot && ['/profile', '/help', '/signout'].some(p => pathname.startsWith(p));

  function PortalMenu({ anchorRef, isOpen, alignRight, children }: { anchorRef: React.RefObject<HTMLElement | null>; isOpen: boolean; alignRight?: boolean; children: React.ReactNode; }) {
    const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);

    useLayoutEffect(() => {
      if (!isOpen) return setPos(null);

      const updatePosFromEl = (elNode: HTMLElement | null) => {
        if (!elNode) return;
        const r = elNode.getBoundingClientRect();
        const top = r.bottom + window.scrollY;
        const left = r.left + window.scrollX;
        setPos({ top, left, width: r.width });
      };

      // Initial set
      updatePosFromEl(anchorRef.current);

      function onResize() {
        updatePosFromEl(anchorRef.current);
      }

      window.addEventListener("resize", onResize);
      window.addEventListener("scroll", onResize, true);
      return () => {
        window.removeEventListener("resize", onResize);
        window.removeEventListener("scroll", onResize, true);
      };
    }, [isOpen, anchorRef]);

    if (!isOpen || !pos) return null;

    const style: React.CSSProperties = {
      position: "absolute",
      top: pos.top,
      left: alignRight ? undefined : pos.left,
      right: alignRight ? Math.max(document.documentElement.clientWidth - (pos.left + pos.width), 8) : undefined,
      background: "rgba(0,0,0,0.95)",
      color: "white",
      boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
      padding: 8,
      minWidth: 180,
      zIndex: 10000,
    };

    return createPortal(<div style={style}>{children}</div>, document.body);
  }

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (programsRef.current && !programsRef.current.contains(e.target as Node)) {
        setProgramsOpen(false);
      }
      if (communityRef.current && !communityRef.current.contains(e.target as Node)) {
        setCommunityOpen(false);
      }
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setProfileOpen(false);
      }
    }
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, []);

  // Responsive detection for mobile menu
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)');
    const set = () => {
      setIsMobile(!!mq.matches);
      if (!mq.matches) {
        setMobileMenuOpen(false);
        setProgramsMobileOpen(false);
        setCommunityMobileOpen(false);
      }
    };
    set();
    const handler = () => set();
    mq.addEventListener?.('change', handler);
    window.addEventListener('resize', handler);
    return () => {
      mq.removeEventListener?.('change', handler);
      window.removeEventListener('resize', handler);
    };
  }, []);

  return (
    <header style={{ borderBottom: '1px solid #eee', position: 'relative' }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '12px 48px', whiteSpace: 'nowrap' }}>
        {/* Left: logo (hidden on mobile, moved to center) */}
        <div style={{ flex: '0 0 auto' }}>
          {!isMobile && (
            <Link
              href="/"
              style={{ fontWeight: 700, fontSize: 18, whiteSpace: 'nowrap', transition: 'transform 120ms ease' }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
            >
              AIHM
            </Link>
          )}
        </div>

        {/* Center: main nav - centered (on mobile: logo + profile centered) */}
        <div style={{ flex: '1 1 auto', display: isMobile ? 'flex' : 'flex', justifyContent: isMobile ? 'center' : 'center' }}>
          {!isMobile ? (
            <nav style={{ display: 'flex', gap: 28, alignItems: 'center', flexWrap: 'nowrap' }}>
              <Link
                href="/workouts"
                style={{
                  whiteSpace: 'nowrap',
                  transition: 'color 150ms ease, transform 120ms ease, box-shadow 180ms ease',
                  boxShadow: startActive ? '0 18px 60px rgba(0,0,0,0.30)' : undefined,
                  background: startActive ? 'rgba(255,255,255,0.05)' : undefined,
                  borderRadius: startActive ? 10 : undefined,
                  padding: startActive ? '6px 10px' : undefined,
                  color: startActive ? 'white' : undefined,
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
              >
                Start Workout
              </Link>

              <div ref={programsRef} style={{ position: 'relative' }}>
                <button
                  ref={programsBtnRef}
                  onClick={() => setProgramsOpen(v => !v)}
                  style={{
                    whiteSpace: 'nowrap',
                    transition: 'color 150ms ease, transform 120ms ease, box-shadow 180ms ease',
                    boxShadow: isProgramsActive ? '0 18px 60px rgba(0,0,0,0.30)' : undefined,
                    background: isProgramsActive ? 'rgba(255,255,255,0.05)' : undefined,
                    borderRadius: isProgramsActive ? 10 : undefined,
                    padding: isProgramsActive ? '6px 10px' : undefined,
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
                >
                  Programs ▾
                </button>
                <PortalMenu anchorRef={programsBtnRef} isOpen={programsOpen}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <Link href="/browsePrograms" style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Browse Programs</Link>
                    <Link href="/programs" style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Current Programs</Link>
                    <Link href="/progress" style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Progress</Link>
                  </div>
                </PortalMenu>
              </div>

              <div ref={communityRef} style={{ position: 'relative' }}>
                <button
                  ref={communityBtnRef}
                  onClick={() => setCommunityOpen(v => !v)}
                  style={{
                    whiteSpace: 'nowrap',
                    transition: 'color 150ms ease, transform 120ms ease, box-shadow 180ms ease',
                    boxShadow: communityActive ? '0 18px 60px rgba(0,0,0,0.30)' : undefined,
                    background: communityActive ? 'rgba(255,255,255,0.05)' : undefined,
                    borderRadius: communityActive ? 10 : undefined,
                    padding: communityActive ? '6px 10px' : undefined,
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
                >
                  Community ▾
                </button>
                <PortalMenu anchorRef={communityBtnRef} isOpen={communityOpen}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <Link href="/community" style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Forums & Challenges</Link>
                    <Link href="/friends" style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Friends</Link>
                  </div>
                </PortalMenu>
              </div>
              <Link
                href="/notifications"
                style={{
                  whiteSpace: 'nowrap',
                  transition: 'color 150ms ease, transform 120ms ease, box-shadow 180ms ease',
                  boxShadow: notificationsActive ? '0 18px 60px rgba(0,0,0,0.30)' : undefined,
                  background: notificationsActive ? 'rgba(255,255,255,0.05)' : undefined,
                  borderRadius: notificationsActive ? 10 : undefined,
                  padding: notificationsActive ? '6px 10px' : undefined,
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
              >
                Notifications
              </Link>
            </nav>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Link href="/" style={{ fontWeight: 700, fontSize: 18, color: 'white', textDecoration: 'none' }}>AIHM</Link>
            </div>
          )}
        </div>

        {/* Right: notifications + profile (and hamburger on mobile) */}
        <div style={{ flex: '0 0 auto', display: 'flex', gap: 20, alignItems: 'center' }}>
          {isMobile && (
            <button aria-label="Open menu" onClick={() => setMobileMenuOpen(v => !v)} style={{ whiteSpace: 'nowrap' }}>
              ☰
            </button>
          )}

          {!isMobile && (
            <div ref={profileRef} style={{ position: 'relative' }}>
              <button
                ref={profileBtnRef}
                onClick={() => setProfileOpen(v => !v)}
                style={{
                  whiteSpace: 'nowrap',
                  transition: 'transform 120ms ease, box-shadow 180ms ease',
                  transform: '',
                  boxShadow: profileActive ? '0 18px 60px rgba(0,0,0,0.30)' : undefined,
                  background: profileActive ? 'rgba(255,255,255,0.05)' : undefined,
                  borderRadius: profileActive ? 10 : undefined,
                  padding: profileActive ? '6px 10px' : undefined,
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
              >
                Profile ▾
              </button>
              <PortalMenu anchorRef={profileBtnRef} isOpen={profileOpen} alignRight>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <Link href="/profile" style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Profile Settings</Link>
                  <Link href="/help" style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Help / Docs</Link>
                  <Link href="/signout" style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Sign out</Link>
                </div>
              </PortalMenu>
            </div>
          )}
        </div>
      </div>

      {/* Mobile menu panel (simple vertical menu) */}
      {isMobile && mobileMenuOpen && (
        <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, background: 'rgba(0,0,0,0.85)', color: 'white', padding: 12, boxShadow: '0 6px 18px rgba(0,0,0,0.08)', zIndex: 9999 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Link
              href="/workouts"
              onClick={() => { setMobileMenuOpen(false); setActiveFor('workout'); }}
              style={{ whiteSpace: 'nowrap', color: activeMobileTop && activeMobileTop !== 'workout' ? 'rgba(255,255,255,0.6)' : 'white', transition: 'color 150ms ease' }}
            >
              Start Workout
            </Link>

            <div>
              <button
                onClick={() => { toggleProgramsMobile(); setActiveFor(programsMobileOpen ? null : 'programs'); }}
                style={{ width: '100%', textAlign: 'left', color: activeMobileTop === 'programs' ? 'white' : 'rgba(255,255,255,0.6)', background: 'transparent', border: 'none', transition: 'color 180ms ease' }}
              >
                Programs ▾
              </button>

              <div style={{ overflow: 'hidden', maxHeight: programsMobileOpen ? 240 : 0, opacity: programsMobileOpen ? 1 : 0, transition: 'max-height 220ms ease, opacity 180ms ease' }}>
                <div style={{ paddingLeft: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <Link href="/browsePrograms" onClick={() => { setMobileMenuOpen(false); setProgramsMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Browse Programs</Link>
                  <Link href="/programs" onClick={() => { setMobileMenuOpen(false); setProgramsMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Current Programs</Link>
                  <Link href="/progress" onClick={() => { setMobileMenuOpen(false); setProgramsMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Progress</Link>
                </div>
              </div>
            </div>

            <div>
              <button
                onClick={() => { toggleCommunityMobile(); setActiveFor(communityMobileOpen ? null : 'community'); }}
                style={{ width: '100%', textAlign: 'left', color: activeMobileTop === 'community' ? 'white' : 'rgba(255,255,255,0.6)', background: 'transparent', border: 'none', transition: 'color 180ms ease' }}
              >
                Community ▾
              </button>
              <div style={{ overflow: 'hidden', maxHeight: communityMobileOpen ? 200 : 0, opacity: communityMobileOpen ? 1 : 0, transition: 'max-height 220ms ease, opacity 180ms ease' }}>
                <div style={{ paddingLeft: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <Link href="/community" onClick={() => { setMobileMenuOpen(false); setCommunityMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Forums & Challenges</Link>
                  <Link href="/friends" onClick={() => { setMobileMenuOpen(false); setCommunityMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Friends</Link>
                </div>
              </div>
            </div>
            {/* Notifications (mobile) — placed after Community, before Profile */}
            <Link
              href="/notifications"
              onClick={() => { setMobileMenuOpen(false); setActiveFor('notifications'); }}
              style={{ color: activeMobileTop === 'notifications' ? 'white' : 'rgba(255,255,255,0.6)', transition: 'color 180ms ease' }}
            >
              Notifications
            </Link>
            {/* Profile dropdown for mobile (inside hamburger) */}
            <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 10 }}>
              <button
                onClick={() => { toggleProfileMobile(); setActiveFor(profileMobileOpen ? null : 'profile'); }}
                style={{ width: '100%', textAlign: 'left', color: activeMobileTop === 'profile' ? 'white' : 'rgba(255,255,255,0.6)', background: 'transparent', border: 'none', transition: 'color 180ms ease' }}
              >
                Profile ▾
              </button>
              <div style={{ overflow: 'hidden', maxHeight: profileMobileOpen ? 160 : 0, opacity: profileMobileOpen ? 1 : 0, transition: 'max-height 220ms ease, opacity 180ms ease' }}>
                <div style={{ paddingLeft: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <Link href="/profile" onClick={() => { setMobileMenuOpen(false); setProfileMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Profile Settings</Link>
                  <Link href="/help" onClick={() => { setMobileMenuOpen(false); setProfileMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Help / Docs</Link>
                  <Link href="/signout" onClick={() => { setMobileMenuOpen(false); setProfileMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Sign out</Link>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
