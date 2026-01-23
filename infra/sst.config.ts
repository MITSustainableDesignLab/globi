/// <reference path="./.sst/platform/config.d.ts" />

export default $config({
  app(input) {
    return {
      name: "globi",
      removal: input?.stage === "production" ? "retain" : "remove",
      protect: ["production"].includes(input?.stage),
      home: "aws",
    };
  },
  async run() {
    const vpc = new sst.aws.Vpc("Vpc");

    const cluster = new sst.aws.Cluster("Cluster", {
      vpc,
    });

    const hatchetToken = new sst.Secret(
      "HATCHET_CLIENT_TOKEN",
      process.env.HATCHET_CLIENT_TOKEN,
    );

    const normalizeName = (name: string, sep: string = "-") => {
      return `${sep === "/" ? "/" : ""}${$app.name}${sep}${
        $app.stage
      }${sep}${name}`;
    };

    const hatchetTokenSecret = new aws.ssm.Parameter(
      normalizeName("HATCHET_CLIENT_TOKEN", "/"),
      {
        type: "SecureString",
        value: hatchetToken.value,
      },
    );

    sst.Linkable.wrap(aws.s3.BucketV2, (bucket) => ({
      properties: { name: bucket.bucket },
      include: [
        sst.aws.permission({
          actions: ["s3:*"],
          resources: [bucket.arn, $interpolate`${bucket.arn}/*`],
        }),
      ],
    }));

    const bucket = process.env.EXISTING_BUCKET
      ? aws.s3.BucketV2.get("Storage", process.env.EXISTING_BUCKET)
      : new sst.aws.Bucket("Storage");

    const bucketName =
      bucket instanceof aws.s3.BucketV2 ? bucket.bucket : bucket.name;

    const args = {
      EP_VERSION: "22.2.0",
      PYTHON_VERSION: "3.12",
    };
    const simCount = process.env.SIM_COUNT
      ? parseInt(process.env.SIM_COUNT)
      : 0;
    const fanCount = process.env.FAN_COUNT
      ? parseInt(process.env.FAN_COUNT)
      : 0;
    const usePrebuiltImages = true;
    const imageTag = `${process.env.AWS_ACCOUNT_ID}.dkr.ecr.${process.env.AWS_REGION}.amazonaws.com/hatchet/globi:latest`;
    const simService = new sst.aws.Service("Simulations", {
      cluster,
      loadBalancer: undefined,

      cpu: "2 vCPU",
      memory: "8 GB",
      capacity: "spot",
      scaling: {
        min: simCount,
        max: simCount,
      },
      image: usePrebuiltImages
        ? imageTag
        : {
            dockerfile: "src/globi/worker/Dockerfile",
            context: "..",
            args,
          },
      environment: {
        SCYTHE_WORKER_DOES_LEAF: "True",
        SCYTHE_WORKER_DOES_FAN: "False",
        // SCYTHE_WORKER_MAX_RUNS: "1",
        SCYTHE_WORKER_SLOTS: "1",
        SCYTHE_STORAGE_BUCKET: bucketName,
        SCYTHE_STORAGE_BUCKET_PREFIX: "globi",
        SCYTHE_TIMEOUT_SCATTER_GATHER_SCHEDULE: "10h",
        SCYTHE_TIMEOUT_SCATTER_GATHER_EXECUTION: "10h",
        SCYTHE_TIMEOUT_EXPERIMENT_SCHEDULE: "10h",
      },
      ssm: {
        HATCHET_CLIENT_TOKEN: hatchetTokenSecret.arn,
      },
      link: [bucket],
    });

    const fanoutService = new sst.aws.Service("Fanouts", {
      cluster,
      loadBalancer: undefined,

      cpu: "4 vCPU",
      memory: "24 GB",
      capacity: "spot",
      scaling: {
        min: fanCount,
        max: fanCount,
      },
      image: usePrebuiltImages
        ? imageTag
        : {
            dockerfile: "src/globi/worker/Dockerfile",
            context: "..",
            args,
          },
      environment: {
        SCYTHE_WORKER_DOES_LEAF: "False",
        SCYTHE_WORKER_DOES_FAN: "True",
        SCYTHE_WORKER_SLOTS: "4",
        SCYTHE_TIMEOUT_SCATTER_GATHER_SCHEDULE: "10h",
        SCYTHE_TIMEOUT_SCATTER_GATHER_EXECUTION: "10h",
        SCYTHE_TIMEOUT_EXPERIMENT_SCHEDULE: "10h",
      },
      ssm: {
        HATCHET_CLIENT_TOKEN: hatchetTokenSecret.arn,
      },
      link: [bucket],
    });
  },
});
