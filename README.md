# Designing a Secure EKS Architecture with Public & Private ALB Ingress and Split DNS
A hands-on lab to build a production-style AWS EKS architecture with:
- Public + Private Application Load Balancers (ALB)
- AWS Load Balancer Controller (Ingress)
- Split-horizon DNS using Route 53 (public + private hosted zones)
- HTTPS with ACM certificates
- Multiple services exposed via Ingress
- Clear security boundaries between internet-facing and internal APIs

In this lab, we are trying to setup infra for 2 kinds of traffic on the same application- public traffic and private traffic.  
Many applications have some APIs exposed to the internet (like frontend pages, certain forms, etc) -> this is public.  
And some APIs are private or internal to a network (like user data, order details, access data, etc) -> this is private.  
As part of this, we are also touch-basing on domains and DNS, using goDaddy and route 53.  

## High-level Architecture
```
Internet
   |
   |  HTTPS
   v
Route 53 (Public Hosted Zone)
   |
   v
Public ALB (internet-facing)
   |
   v
Kubernetes Ingress (AWS Load Balancer Controller)
   |
   v
Public Frontend Service (EKS Pods)


VPC (Private Network)
   |
   v
Route 53 (Private Hosted Zone)
   |
   v
Internal ALB (internal)
   |
   v
Kubernetes Ingress (AWS Load Balancer Controller)
   |
   v
Internal API Service (EKS Pods)
```
## Application files
There are 2 components, seperated into 2 folders in this repo:
- frontend: This one is public. It serves `/` and `/hello` endpoints
- internal: This one is private. It serves `/hobbies` and `/secrets` endpoints

## PHASE 1 - Build & push images to ECR
**Create Repository**
1. Go to ECR
2. Click Create repository
3. Choose:  
  Visibility: Private  
  Repository name: `public-frontend`
  Click Create repository

  Do the same for another repository named `internal-api`

**Build, Tag, Push Your Docker Image to ECR**
```
# Frontend
cd frontend
docker build -t public-frontend:1.0 .
docker tag public-frontend:1.0 <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/public-frontend:1.0
docker push <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/public-frontend:1.0

# Internal
cd ../internal
docker build -t internal-api:1.0 .
docker tag internal-api:1.0 <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/internal-api:1.0
docker push <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/internal-api:1.0
```

After this:
- Go back to ECR Console
- Open repo → Images
- You should see 1.0

## PHASE 2 – Create VPC (Network)
1. Go to VPC
2. Click Create VPC
3. Choose VPC and more
4. Fill:
```
| Setting               | Value              |
| --------------------- | ------------------ |
| Name                  | eks-vpc            |
| IPv4 CIDR             | default            |
| AZs                   | 2                  |
| Public subnets        | 2                  |
| Private subnets       | 2                  |
| NAT gateways          | 1 (to reduce cost) |
| VPC endpoints         | None               |
| Enable DNS Hostanames | Yes                |
```
5. Click Create VPC. Wait till status = `Available`

## PHASE 3 - Buy a domain on GoDaddy
The process to buy a domain is pretty straight forward on GoDaddy.
As part of this phase, buy a domain. In this lab, we will assume we bought the domain- chandaninbeta.live  

## PHASE 4 - Route 53 public hosted zone & GoDaddy nameservers
### Create public hosted zone
Console → Route 53 → Hosted zones → Create hosted zone:
- Domain name: `chandaninbeta.live`
- Type: Public hosted zone
- Click Create. You'll see 4 NS records (copy them).

### Update GoDaddy nameservers
GoDaddy → My Products → Domain → DNS → Nameservers → Change → Custom → paste the 4 AWS NS values → Save.  
Wait ~5–30 minutes for DNS propagation.  
Verify:
```
nslookup chandaninbeta.live
# or dig +short NS chandaninbeta.live
```

## PHASE 5 - Create EKS Cluster
1. Go to EKS
2. Click Add cluster → Create
3. Do not choose the auto-mode as it incurs extra cost, and we don't need its capabilties for this project.
4. Fill:
```
| Field                | Value                              |
| -------------------- | ---------------------------------- |
| Name                 | demo-eks                           |
| Kubernetes version   | default                            |
| Cluster service role | Create new role (default EKS role) |
```
> Make sure the role has the policy 'AmazonEKSClusterPolicy'
4. Click Next
  
**Networking Page:**
- VPC: eks-vpc
- Subnets: Select all private subnets
- Endpoint access: Public and private
5. Leave every other settings/fields as is.
6. Click Create. Takes ~10mins

## PHASE 6 – Add Worker Nodes (EC2)
Your cluster currently has zero machines.
1. EKS → Clusters → demo-eks
2. Go to Compute tab
3. Click Add node group
4. Fill:
```
| Setting         | Value         |
| --------------- | ------------- |
| Node group name | ng-general    |
| Node IAM role   | Create new    |
| Instance type   | t3.small      |
| Desired         | 2             |
| Min             | 1             |
| Max             | 2             |
| Subnets         | priv. subnets |
```
> Make sure the role has these polcies- AmazonEKSWorkerNodePolicy, AmazonEC2ContainerRegistryReadOnly, AmazonEKS_CNI_Policy.
> 
> If you choose instance type as t3.micro, only 4 pods can be scheduled there. Most of the EKS/k8s related pods take up those 4. So your application pod can't be scheduled then.
> Choose t3.small for very basic use like this example.
5. Click Create. Wait till nodes become Active
6. Update kubeconfig:
```
aws eks update-kubeconfig --region ap-south-1 --name demo-eks
kubectl get nodes -o wide
```

## PHASE 7 - Route 53 Private hosted zone
Route 53 → Hosted zones → Create hosted zone  
- Domain name: chandaninbeta.live
- Type: Private hosted zone
- VPC: select the eks-vpc you created (select region ap-south-1)
- Click Create

Now you have TWO hosted zones with the same domain:
- Public hosted zone (public internet)
- Private hosted zone (VPC-resolvable)

You will later add A records to these hosted zones to point to respective ALBs.

## PHASE 8 - Deploy applications & services
In the `frontend-component.yaml` and `internal-component.yaml` files, modify the `image:` field to include your ECR repo.
Apply both the YAMLs using:
```
kubectl apply -f k8s/frontend-deployment.yaml
kubectl apply -f k8s/internal-deployment.yaml
kubectl get pods
kubectl get svc
```
Make sure the pods are up and services are created.

## PHASE 9 - Install AWS Load Balancer Controller (IAM + Helm)
This is critical; it manages ALBs.
1. Associate OIDC provider for the cluster (eksctl makes this easy)
```
eksctl utils associate-iam-oidc-provider \
  --cluster demo-eks \
  --region ap-south-1 \
  --approve
```
2. Create IAM policy for controller
Download the official policy and create it:
```
curl -o iam_policy.json \
  https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json

aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy \
  --policy-document file://iam_policy.json
```
3. Create IAM service account
```
eksctl create iamserviceaccount \
  --cluster demo-eks \
  --namespace kube-system \
  --name aws-load-balancer-controller \
  --attach-policy-arn arn:aws:iam::<ACCOUNT_ID>:policy/AWSLoadBalancerControllerIAMPolicy \
  --approve \
  --region ap-south-1
```
4. Get vpcId
```
aws eks describe-cluster \
  --name demo-eks \
  --region ap-south-1 \
  --query "cluster.resourcesVpcConfig.vpcId" \
  --output text
```
5. Install Helm chart
```
helm repo add eks https://aws.github.io/eks-charts
helm repo update

helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=chandan-eks \
  --set region=ap-south-1 \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller
  --set vpcId=<vpcId you got in previous step>
```
6. Verify
`kubectl get pods -n kube-system | grep aws-load-balancer-controller`  
You should see the controller pod `Running`.
If not running, check if aws-load-balancer-controller deployment and replicaset are up. They would be present in the same namespace (kube-system).  
If they are not up, describe them to see the error.  
If pod is in error state, check the logs of the pod.  
Based on the error message, proceed with the fix.

## PHASE 10 - Create ACM certificate (DNS validation)
- ACM → Request certificate
- Domain names:
- `api.chandaninbeta.live` (this is the public facing subdomain URL)
- Validation: DNS
- Click Create record in Route 53 (ACM can auto-create the CNAME in the public hosted zone)
- Wait for `Issued` status
Important: ACM for public ALB must be in ap-south-1.

## PHASE 11 - Ingress manifests — Public & Private
- In the `ingress-public.yaml` file, replace `<CERT_ARN>` with the issued ACM certificate ARN. Apply this YAML file.
- Wait for ALB creation. Check `kubectl get ingress public-ingress -o wide`.
- The `ADDRESS` column will show ALB DNS (k8s-...ap-south-1.elb.amazonaws.com).
- The `ingress-private.yaml` will create an internal (private) ALB. No TLS required for internal (optional). Apply this YAML file.
- Wait for ALB creation. Check `kubectl get ingress public-ingress -o wide`.
- The `ADDRESS` column shows internal ALB DNS (has .elb.amazonaws.com too but will be internal). Note: internal ALB will be created in your VPC and only routable inside.

## PHASE 12 - Route 53 records — wire hosts to ALB
### After public ingress ALB is ready
Get ALB DNS from:
```
kubectl get ingress public-ingress -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
# or show full
kubectl get ingress -o wide
```
#### Create Public A record (public hosted zone)
Route 53 → Hosted zones → chandaninbeta.live (public) → Create record:
- Record name: api
- Record type: A – IPv4 address
- Alias: Yes
- Route traffic to: Alias to Application Load Balancer
- Choose region: ap-south-1
- Select load balancer (the internet-facing ALB you saw)
- Save

Now `api.chandaninbeta.live` resolves publicly to the ALB.  

### After private ingress ALB is ready
Get internal ALB DNS:
```
kubectl get ingress private-ingress -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
# or show full
kubectl get ingress -o wide
```
#### Create Private A record (private hosted zone)
Route 53 → Hosted zones → chandaninbeta.live (private) → Create record:
- Record name: api-internal
- Record type: A – IPv4 address
- Alias: Yes
- Route traffic to: Alias to Application Load Balancer
- Select internal ALB
- Save

Now from inside the VPC (like from a pod or an EC2 in that VPC), `api-internal.chandaninbeta.live` will resolve to the internal ALB.  
From public internet it will not.

## PHASE 13 - Testing & verification
### Public checks (from your laptop)
```
# DNS resolves to ALB
nslookup api.chandaninbeta.live

# Fetch endpoints via TLS
curl -v https://api.chandaninbeta.live/
curl -v https://api.chandaninbeta.live/hello
```
You should get JSON responses from frontend.

You could also hit these URLs from your browser:
<img width="877" height="377" alt="image" src="https://github.com/user-attachments/assets/d5607e45-02e5-4e71-aa2f-0d3238227baf" />  
The other API:
<img width="894" height="316" alt="image" src="https://github.com/user-attachments/assets/c4df37fa-2bc2-4d3d-892e-876eae48370d" />

### Private checks (from inside a pod)
Pick any pod (like a debug pod) and exec into it:
```
kubectl run -it --rm --image=amazonlinux:2 debug-shell -- bash
# inside shell: install curl if needed
yum install -y curl
curl -v http://api-internal.chandaninbeta.live/hobbies
curl -v http://api-internal.chandaninbeta.live/secrets
```
These should work (DNS resolves to internal ALB, ALB forwards to internal service).  
<img width="975" height="534" alt="image" src="https://github.com/user-attachments/assets/5df40c11-bf2e-4373-923f-05dab613da93" />

### Private check from laptop (should fail)
```
curl http://api-internal.chandaninbeta.live/hobbies
# this should not resolve or should not route (good - private!)
```
<img width="975" height="62" alt="image" src="https://github.com/user-attachments/assets/9c897e75-3490-41ca-a212-7388ce864ba1" />

Or, hitting the URLs on the browser should also not resolve:
<img width="975" height="506" alt="image" src="https://github.com/user-attachments/assets/16d13645-89ea-445f-98ed-0a99abd8ee08" />

## PHASE 14 - Cleanup (when done)
To avoid AWS costs:
```
# delete k8s resources
kubectl delete -f ingress-public.yaml
kubectl delete -f ingress-private.yaml
kubectl delete -f frontend-component.yaml
kubectl delete -f internal-component.yaml
```
Delete EKS node group first and then the EKS cluster  
Delete NAT GW associated to the VPC.  
Delete VPC.  
In route 53, delete the A record and CNAME created by ACM in the public hosted zone. Then, delete the public hosted zone.  
In route 53, Delete the A record in private hosted zone. Then, delete the private hosted zone.  
Delete the ACM Certificate.  
Delete the ECR Repositories.  
Make sure all EC2 instances, ALBs, ASGs are gone.  

## UP NEXT
Automate all of the above using terraform.

`Ashte`
