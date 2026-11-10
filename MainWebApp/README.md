<a href="https://demo-nextjs-with-supabase.vercel.app/">
  <img alt="Next.js and Supabase Starter Kit - the fastest way to build apps with Next.js and Supabase" src="https://demo-nextjs-with-supabase.vercel.app/opengraph-image.png">
  <h1 align="center">Next.js and Supabase Starter Kit</h1>
</a>

<p align="center">
 The fastest way to build apps with Next.js and Supabase
</p>

<p align="center">
  <a href="#features"><strong>Features</strong></a> ·
  <a href="#demo"><strong>Demo</strong></a> ·
  <a href="#deploy-to-vercel"><strong>Deploy to Vercel</strong></a> ·
  <a href="#clone-and-run-locally"><strong>Clone and run locally</strong></a> ·
  <a href="#feedback-and-issues"><strong>Feedback and issues</strong></a>
  <a href="#more-supabase-examples"><strong>More Examples</strong></a>
</p>
<br/>

## Features

- Works across the entire [Next.js](https://nextjs.org) stack
  - App Router
  - Pages Router
  - Proxy
  - Client
  - Server
  - It just works!
- supabase-ssr. A package to configure Supabase Auth to use cookies
- Password-based authentication block installed via the [Supabase UI Library](https://supabase.com/ui/docs/nextjs/password-based-auth)
- Styling with [Tailwind CSS](https://tailwindcss.com)
- Components with [shadcn/ui](https://ui.shadcn.com/)
- Optional deployment with [Supabase Vercel Integration and Vercel deploy](#deploy-your-own)
  - Environment variables automatically assigned to Vercel project

## Demo

You can view a fully working demo at [demo-nextjs-with-supabase.vercel.app](https://demo-nextjs-with-supabase.vercel.app/).

## Deploy to Vercel

Vercel deployment will guide you through creating a Supabase account and project.

After installation of the Supabase integration, all relevant environment variables will be assigned to the project so the deployment is fully functioning.

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Fvercel%2Fnext.js%2Ftree%2Fcanary%2Fexamples%2Fwith-supabase&project-name=nextjs-with-supabase&repository-name=nextjs-with-supabase&demo-title=nextjs-with-supabase&demo-description=This+starter+configures+Supabase+Auth+to+use+cookies%2C+making+the+user%27s+session+available+throughout+the+entire+Next.js+app+-+Client+Components%2C+Server+Components%2C+Route+Handlers%2C+Server+Actions+and+Middleware.&demo-url=https%3A%2F%2Fdemo-nextjs-with-supabase.vercel.app%2F&external-id=https%3A%2F%2Fgithub.com%2Fvercel%2Fnext.js%2Ftree%2Fcanary%2Fexamples%2Fwith-supabase&demo-image=https%3A%2F%2Fdemo-nextjs-with-supabase.vercel.app%2Fopengraph-image.png)

The above will also clone the Starter kit to your GitHub, you can clone that locally and develop locally.

If you wish to just develop locally and not deploy to Vercel, [follow the steps below](#clone-and-run-locally).

## Clone and run locally

1. You'll first need a Supabase project which can be made [via the Supabase dashboard](https://database.new)

2. Create a Next.js app using the Supabase Starter template npx command

   ```bash
   npx create-next-app --example with-supabase with-supabase-app
   ```

   ```bash
   yarn create next-app --example with-supabase with-supabase-app
   ```

   ```bash
   pnpm create next-app --example with-supabase with-supabase-app
   ```

3. Use `cd` to change into the app's directory

   ```bash
   cd with-supabase-app
   ```

4. Rename `.env.example` to `.env.local` and update the following:

  ```env
  NEXT_PUBLIC_SUPABASE_URL=[INSERT SUPABASE PROJECT URL]
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=[INSERT SUPABASE PROJECT API PUBLISHABLE OR ANON KEY]
  NEXT_PUBLIC_SITE_URL=[INSERT APP ORIGIN, FOR EXAMPLE http://localhost:3000]
  SITE_URL=[OPTIONAL SERVER-SIDE OVERRIDE FOR HOSTED DEPLOYMENTS]
  NEXT_PUBLIC_TURNSTILE_SITE_KEY=[OPTIONAL LOCALLY, REQUIRED IN PRODUCTION FOR AUTH FORMS]
  TURNSTILE_SECRET_KEY=[OPTIONAL LOCALLY, REQUIRED IN PRODUCTION FOR AUTH FORMS]
  ```
  > [!NOTE]
  > This example uses `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, which refers to Supabase's new **publishable** key format.
  > Both legacy **anon** keys and new **publishable** keys can be used with this variable name during the transition period. Supabase's dashboard may show `NEXT_PUBLIC_SUPABASE_ANON_KEY`; its value can be used in this example.
  > See the [full announcement](https://github.com/orgs/supabase/discussions/29260) for more information.

  Both `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` can be found in [your Supabase project's API settings](https://supabase.com/dashboard/project/_?showConnect=true)

  `NEXT_PUBLIC_SITE_URL` and `SITE_URL` are used when the app constructs auth confirmation and reset callback URLs. In Vercel, set one of them to your canonical deployment origin so email links resolve consistently.

  `NEXT_PUBLIC_TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY` are used by the login, signup, forgot-password, and update-password forms. In development those checks can be skipped when unset, but production auth flows will reject requests until both keys are configured.

5. If you deploy on Vercel, add the same environment variables to the Vercel project settings for Production and Preview as needed.

6. In Supabase Auth URL configuration, include redirect URLs for both local and deployed environments, including the `/auth/confirm` callback route.

   ```text
   http://localhost:3000/auth/confirm
   https://your-production-domain/auth/confirm
   https://your-preview-domain/auth/confirm
   ```

7. You can now run the Next.js local development server:

   ```bash
   npm run dev
   ```

   The starter kit should now be running on [localhost:3000](http://localhost:3000/).

8. This template comes with the default shadcn/ui style initialized. If you instead want other ui.shadcn styles, delete `components.json` and [re-install shadcn/ui](https://ui.shadcn.com/docs/installation/next)

> Check out [the docs for Local Development](https://supabase.com/docs/guides/getting-started/local-development) to also run Supabase locally.

## Workout Pipeline

The workout dataset flow now has a single sequential runner:

```bash
c:/Users/BB/VSCodeProjects/AiHM/aihm/.venv/Scripts/python.exe main_training.py --input-root preprocessedWorkoutVideos --extracted-root generated/workout-pose-dataset --model-path generated/workout-models/workout-centroid-model.json
```

You can also choose which angle vectors the trainer uses with `--feature-mode 2d`, `--feature-mode 3d`, or `--feature-mode both`.

If you want a comparison in the saved model artifact, add `--benchmark-feature-mode 2d` and/or `--benchmark-feature-mode 3d` to the same command.

If you want to drive the pipeline from a CSV file that you download and edit on iPhone, use the template at [workout-import-template.csv](workout-import-template.csv) and pass it into the runner:

```bash
c:/Users/BB/VSCodeProjects/AiHM/aihm/.venv/Scripts/python.exe main_training.py --manifest-csv workout-import-template.csv
```

The CSV uses `relative_path`, `exercise_key`, and `include` columns so you can keep the file simple and deterministic.

That script runs extraction, training, and prediction in order. The lower-level scripts are still available if you want to run a single stage by itself:

The training report now includes per-split `predictedCounts`, per-class precision/recall/F1, and a confusion matrix so you can see which exercises are being mixed up instead of only looking at one overall accuracy number. The trainer also splits clips in a class-stratified way so rare exercises stay represented in train, validation, and test, and it exposes an optional `--max-windows-per-clip` cap if you want to reduce redundant overlapping windows from long clips. The extracted `clip.json` and `windows.jsonl` records also include `contractionAngleNames`, `contractionScore2d`, `contractionScore3d`, `contractionScore`, and `contractionState` so the model has an exercise-aware contracted/relaxed signal alongside the joint angles.

1. Extract pose features from the workout video folders.

  ```bash
  c:/Users/BB/VSCodeProjects/AiHM/aihm/.venv/Scripts/python.exe scripts/extract_workout_pose_dataset.py
  ```

2. Train the baseline exercise classifier from the extracted windows.

  ```bash
  c:/Users/BB/VSCodeProjects/AiHM/aihm/.venv/Scripts/python.exe scripts/train_workout_classifier.py --windows generated/workout-pose-dataset --output-model generated/workout-models/workout-centroid-model.json
  ```

3. Predict a workout label from a processed clip.

  ```bash
  c:/Users/BB/VSCodeProjects/AiHM/aihm/.venv/Scripts/python.exe scripts/predict_workout_exercise.py --model generated/workout-models/workout-centroid-model.json --clip "generated/workout-pose-dataset/barbellBicepsCurl/barbell biceps curl_1.json" --window-family short
  ```

4. Run the live causal pipeline on a webcam or video file.

  ```bash
  c:/Users/BB/VSCodeProjects/AiHM/aihm/.venv/Scripts/python.exe scripts/run_live_workout_pipeline.py --video "preprocessedWorkoutVideos/decline bench press/dbp_2.MOV" --max-frames 30
  ```

The extractor normalizes `.mov` inputs through `imageio-ffmpeg` when needed, so iPhone uploads can run through the same pipeline as `.mp4` files.

## Feedback and issues

Please file feedback and issues over on the [Supabase GitHub org](https://github.com/supabase/supabase/issues/new/choose).

## More Supabase examples

- [Next.js Subscription Payments Starter](https://github.com/vercel/nextjs-subscription-payments)
- [Cookie-based Auth and the Next.js 13 App Router (free course)](https://youtube.com/playlist?list=PL5S4mPUpp4OtMhpnp93EFSo42iQ40XjbF)
- [Supabase Auth and the Next.js App Router](https://github.com/supabase/supabase/tree/master/examples/auth/nextjs)
