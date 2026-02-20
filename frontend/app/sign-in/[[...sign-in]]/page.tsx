import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <main className="container">
      <SignIn />
    </main>
  );
}
