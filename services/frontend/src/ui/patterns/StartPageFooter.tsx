export function StartPageFooter() {
  return (
    <footer className="relative start-1/2 mt-auto w-screen shrink-0 -translate-x-1/2 bg-white shadow-[0_-2px_6px_rgba(0,0,0,0.08)] rtl:translate-x-1/2">
      <div className="mx-auto grid w-full max-w-app grid-cols-2 items-center gap-x-4 px-5 py-6 sm:gap-x-12 sm:px-8 lg:gap-x-28 lg:px-12">
        <img
          src="/assets/Foerdermittelgeber.png"
          alt="Fördermittelgeber"
          className="h-auto w-full max-w-[389px] justify-self-start"
        />
        <img
          src="/assets/Stadt.png"
          alt="Stadt Kassel"
          className="h-auto w-full max-w-[388px] justify-self-end"
        />
      </div>
    </footer>
  );
}
